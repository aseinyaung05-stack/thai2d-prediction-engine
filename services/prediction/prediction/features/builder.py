"""Causally-safe feature generation.

HARD RULE (spec: WALK-FORWARD FEATURE GENERATION):
For a prediction at chronological position t, every statistic below is
computed exclusively from observations with index < t. The builder maintains
incremental state and emits one Snapshot per step; the target (actual result)
is attached for supervision but is NEVER an input to any feature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

N_NUMBERS = 100
SECTION_BOUNDS = {"A": (0, 24), "B": (25, 49), "C": (50, 74), "D": (75, 99)}
WINDOWS = (7, 14, 30, 60, 100, 250)

FEATURE_NAMES = [
    *[f"freq_{w}" for w in WINDOWS],
    "ewf",
    "days_since_number",
    "days_since_tens",
    "days_since_ones",
    "markov_number",
    "markov_tens",
    "markov_ones",
    "same_tens_as_prev",
    "same_ones_as_prev",
    "is_reverse_of_prev",
    "dist_to_prev",
    "dist_to_reverse_prev",
    "same_tens_prev_session",
    "same_ones_prev_session",
    "matches_set_frac_digits",
    "dist_to_set_frac_digits",
    "set_value_norm",
    "set_change",
    "set_direction",
    "market_value_norm",
    "dow_sin",
    "dow_cos",
]

#: Single source of truth: feature name -> column index.
FEATURE_INDEX = {name: i for i, name in enumerate(FEATURE_NAMES)}


def classify_section(n: int) -> str:
    for s, (lo, hi) in SECTION_BOUNDS.items():
        if lo <= n <= hi:
            return s
    raise ValueError(f"Out of range: {n}")


def section_of_array(numbers: np.ndarray) -> np.ndarray:
    return np.vectorize(classify_section)(numbers)


@dataclass
class Snapshot:
    """One causally-built prediction point."""

    index: int                      # chronological position in the stream
    ts: pd.Timestamp                # source timestamp of the NEXT (unknown) draw
    date: object                    # Myanmar-local date of the next draw
    session: str                    # which stream this prediction targets
    X: np.ndarray                   # (100, F) candidate feature matrix
    feature_names: list[str]
    target: Optional[int]           # actual next number (None when predicting live)
    prev_number: int                # most recent observed number (any session)
    prev_same_session_number: int   # previous draw within the SAME session stream
    prev_cross_session_number: int = -1  # most recent draw of the OTHER session
    context: dict = field(default_factory=dict)


class CausalFeatureBuilder:
    """Incremental, leak-proof feature generator.

    Usage:
        snapshots = CausalFeatureBuilder().build_snapshots(df, session="MORNING")
    Each snapshot's X depends only on rows strictly before its own position.
    """

    def __init__(self, halflife: int = 30, laplace_alpha: float = 1.0,
                 min_history: int = 30, max_snapshots: int | None = None):
        self.halflife = max(1, halflife)
        self.alpha = float(laplace_alpha)
        self.min_history = min_history
        self.max_snapshots = max_snapshots

    # ------------------------------------------------------------------ core

    def build_snapshots(self, df: pd.DataFrame, session: str | None = None) -> list[Snapshot]:
        if df.empty:
            return []
        df = df.sort_values("ts").reset_index(drop=True)
        n = len(df)

        # Incremental state (all derived from rows < current t only).
        counts = np.zeros(N_NUMBERS)                     # overall frequency
        ew_weights = np.zeros(N_NUMBERS)                 # exponential-weight mass
        tens_counts = np.zeros(10)
        ones_counts = np.zeros(10)
        trans_num = np.full((N_NUMBERS, N_NUMBERS), self.alpha)     # Laplace prior
        trans_tens = np.full((10, 10), self.alpha)
        trans_ones = np.full((10, 10), self.alpha)
        last_seen_number = np.full(N_NUMBERS, -10**9)
        last_seen_tens = np.full(10, -10**9)
        last_seen_ones = np.full(10, -10**9)
        window: list[int] = []                           # trailing raw numbers
        prev_set_value: float | None = None
        prev_session_number: dict[str, int] = {}

        decay = 0.5 ** (1.0 / self.halflife)
        snapshots: list[Snapshot] = []
        start = max(self.min_history, 1)
        other_session: str | None = None
        if session is not None:
            other_session = "AFTERNOON" if session == "MORNING" else "MORNING"
        prev_core_number: int | None = None

        def advance_state(t: int) -> None:
            """Fold row t into incremental state. Called ONLY after the
            snapshot for position t has been emitted (strict causality).

            With `session` set, ONLY that session's rows feed the core
            frequency/recency/Markov stream (spec §11: never combine both
            sessions blindly). Rows of the other session update only the
            cross-session context (prev_session_number) and SET context.
            """
            nonlocal prev_set_value, ew_weights, prev_core_number
            row = df.iloc[t]
            num = int(row["number"])
            tens, ones = divmod(num, 10)
            is_core = session is None or str(row["session"]) == session
            if is_core:
                ew_weights *= decay
                ew_weights[num] += 1.0
                counts[num] += 1
                tens_counts[tens] += 1
                ones_counts[ones] += 1
                if prev_core_number is not None:
                    ptens, pones = divmod(prev_core_number, 10)
                    trans_num[prev_core_number][num] += 1
                    trans_tens[ptens][tens] += 1
                    trans_ones[pones][ones] += 1
                last_seen_number[num] = t
                last_seen_tens[tens] = t
                last_seen_ones[ones] = t
                window.append(num)
                if len(window) > max(WINDOWS):
                    window.pop(0)
                prev_core_number = num
            sv = row["set_value"]
            prev_set_value = float(sv) if pd.notna(sv) else None
            prev_session_number[str(row["session"])] = num

        # Warm-up: load rows [0, start) so the first emitted snapshot already
        # sees full prior history (causal — these are all strictly earlier).
        for wu in range(start):
            advance_state(wu)

        # Emission points: only rows belonging to the requested session when
        # one is set (each snapshot predicts ITS OWN session's next draw).
        candidate_positions = [
            t for t in range(start, n)
            if session is None or str(df.iloc[t]["session"]) == session
        ]
        selected: set[int] = set(candidate_positions)
        if self.max_snapshots and len(selected) > self.max_snapshots:
            # Subsample evaluation points evenly (keeps walk-forward tractable
            # while preserving strict chronology).
            step = max(1, len(candidate_positions) // self.max_snapshots)
            selected = set(candidate_positions[::step])
            selected.add(candidate_positions[-1])

        # Walk EVERY row chronologically: non-session rows still advance the
        # cross-session context; session rows emit snapshots (when selected)
        # and then advance the core stream. State at emit time reflects
        # strictly earlier rows only.
        for t in range(start, n):
            row_session = str(df.iloc[t]["session"])
            is_core_row = session is None or row_session == session
            if is_core_row and t in selected:
                row = df.iloc[t]
                pred_session = session or row_session
                same_prev = prev_session_number.get(pred_session)
                cross_prev = None
                if other_session is not None:
                    cross_prev = prev_session_number.get(other_session)
                if cross_prev is None:
                    cross_prev = same_prev if same_prev is not None else int(df.iloc[t - 1]["number"])

                X = self._candidate_matrix(
                    counts=counts,
                    ew_weights=ew_weights,
                    tens_counts=tens_counts,
                    ones_counts=ones_counts,
                    trans_num=trans_num,
                    trans_tens=trans_tens,
                    trans_ones=trans_ones,
                    last_seen_number=last_seen_number,
                    last_seen_tens=last_seen_tens,
                    last_seen_ones=last_seen_ones,
                    window=window,
                    prev_row=df.iloc[t - 1],
                    prev_set_value=prev_set_value,
                    prev_cross_session=cross_prev,
                    dow=pd.Timestamp(row["date"]).weekday(),
                    total_mass=max(1.0, ew_weights.sum()),
                    count_total=float(t),
                )
                snapshots.append(
                    Snapshot(
                        index=t,
                        ts=pd.Timestamp(row["ts"]),
                        date=row["date"],
                        session=pred_session,
                        X=X,
                        feature_names=list(FEATURE_NAMES),
                        target=int(row["number"]),
                        prev_number=int(df.iloc[t - 1]["number"]),
                        prev_same_session_number=same_prev if same_prev is not None else -1,
                        prev_cross_session_number=cross_prev,
                        context={
                            "prev_set_value": prev_set_value,
                            "history_rows": t,
                            "source_data_cutoff": pd.Timestamp(df.iloc[t - 1]["ts"]),
                        },
                    )
                )

            # ---- state advances for EVERY row, AFTER any snapshot above ----
            advance_state(t)

        return snapshots

    def final_snapshot(
        self,
        df: pd.DataFrame,
        session: str,
        next_date=None,
        next_ts=None,
    ) -> Snapshot:
        """Live-prediction snapshot using ALL available history (< cutoff)."""
        snaps = self.build_snapshots_with_extra_row(df, session, next_date, next_ts)
        return snaps[-1]

    def build_snapshots_with_extra_row(
        self,
        df: pd.DataFrame,
        session: str,
        next_date=None,
        next_ts=None,
    ) -> list[Snapshot]:
        """Append a placeholder row so the final snapshot predicts the future
        draw without consuming it (target stays unknown)."""
        df = df.sort_values("ts").reset_index(drop=True)
        if df.empty:
            raise ValueError("No history available for live snapshot.")
        placeholder = pd.DataFrame(
            [
                {
                    "ts": next_ts if next_ts is not None else df["ts"].iloc[-1],
                    "date": next_date if next_date is not None else df["date"].iloc[-1],
                    "session": session,
                    "number": -1,
                    "tens": -1,
                    "ones": -1,
                    "set_value": np.nan,
                    "market_value": np.nan,
                }
            ]
        )
        combined = pd.concat([df, placeholder], ignore_index=True)
        snaps = self.build_snapshots(combined, session=session)
        snaps[-1].target = None
        return snaps

    # ------------------------------------------------------------- internals

    def _candidate_matrix(
        self,
        *,
        counts,
        ew_weights,
        tens_counts,
        ones_counts,
        trans_num,
        trans_tens,
        trans_ones,
        last_seen_number,
        last_seen_tens,
        last_seen_ones,
        window,
        prev_row,
        prev_set_value,
        prev_cross_session,
        dow: int,
        total_mass: float,
        count_total: float,
    ) -> np.ndarray:
        numbers = np.arange(N_NUMBERS)
        tens_digits = numbers // 10
        ones_digits = numbers % 10

        feats: list[np.ndarray] = []

        # --- frequency features (windowed) ---
        w_arr = np.asarray(window if window else [-1], dtype=int)
        for w in WINDOWS:
            recent = w_arr[-w:]
            cw = np.bincount(recent[recent >= 0], minlength=N_NUMBERS)[:N_NUMBERS]
            feats.append(cw / max(1, len(recent)))

        # exponentially weighted frequency (recent draws weigh more)
        feats.append(ew_weights / total_mass)

        # --- recency features (weak signal only — anti gambler's fallacy) ---
        t_now = count_total
        dsn = np.clip(t_now - last_seen_number, 0, 5000)
        dst = np.clip(t_now - last_seen_tens[tens_digits], 0, 5000)
        dso = np.clip(t_now - last_seen_ones[ones_digits], 0, 5000)
        feats.extend([np.log1p(dsn), np.log1p(dst), np.log1p(dso)])

        # --- Markov transition probabilities (Laplace-smoothed) ---
        pnum = int(prev_row["number"])
        ptens, pones = divmod(pnum, 10)
        row_num = trans_num[pnum]
        feats.append(row_num / row_num.sum())
        rt = trans_tens[ptens]
        tens_prob = rt / rt.sum()
        feats.append(tens_prob[tens_digits])
        ro = trans_ones[pones]
        ones_prob = ro / ro.sum()
        feats.append(ones_prob[ones_digits])

        # --- digit relationship features (descriptive, not guarantees) ---
        rev_prev = (pnum % 10) * 10 + pnum // 10
        feats.append((tens_digits == ptens).astype(float))
        feats.append((ones_digits == pones).astype(float))
        feats.append((numbers == rev_prev).astype(float))
        feats.append(np.abs(numbers - pnum) / 99.0)
        feats.append(np.abs(numbers - rev_prev) / 99.0)

        # previous draw of the OTHER session (cross-session relation, §11:
        # prev 4:30 -> next 12:00, prev 12:00 -> same-day 4:30)
        if prev_cross_session is not None and prev_cross_session >= 0:
            pst, pso = divmod(prev_cross_session, 10)
        else:
            pst, pso = ptens, pones  # graceful fallback: reuse immediate prev
        feats.append((tens_digits == pst).astype(float))
        feats.append((ones_digits == pso).astype(float))

        # --- SET-index context features (previous observation, causal) ---
        sv = prev_set_value
        if sv is not None and np.isfinite(sv):
            frac = int(round((sv - np.floor(sv)) * 100)) % 100
            sv_norm = (sv % 1000) / 1000.0
        else:
            frac = -1
            sv_norm = 0.5
        feats.append((numbers == frac).astype(float))
        feats.append(np.abs(numbers - frac) / 99.0 if frac >= 0 else np.zeros(N_NUMBERS))
        feats.append(np.full(N_NUMBERS, sv_norm))
        change = 0.0
        if sv is not None and prev_row.get("set_value") is not None and np.isfinite(
            float(prev_row["set_value"]) if pd.notna(prev_row["set_value"]) else np.nan
        ):
            pv = float(prev_row["set_value"])
            if pv != 0 and np.isfinite(pv) and np.isfinite(sv):
                change = np.tanh((sv - pv) / pv)
        feats.append(np.full(N_NUMBERS, change))
        feats.append(np.full(N_NUMBERS, np.sign(change)))
        mv = prev_row.get("market_value")
        mvn = (float(mv) % 1000) / 1000.0 if mv is not None and pd.notna(mv) and np.isfinite(float(mv)) else 0.5
        feats.append(np.full(N_NUMBERS, mvn))

        # --- calendar encoding ---
        feats.append(np.full(N_NUMBERS, np.sin(2 * np.pi * dow / 5)))
        feats.append(np.full(N_NUMBERS, np.cos(2 * np.pi * dow / 5)))

        assert all(len(f) == N_NUMBERS for f in feats), "feature length mismatch"
        X = np.column_stack(feats)
        assert X.shape[1] == len(FEATURE_NAMES), (
            f"Feature name/table mismatch: {X.shape[1]} vs {len(FEATURE_NAMES)}"
        )
        return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
