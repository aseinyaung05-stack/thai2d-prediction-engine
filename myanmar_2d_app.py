"""
============================================================================
 Myanmar 2D — Live Results & Historical Prediction System
============================================================================
 A production-ready Streamlit application featuring:

   • Strict "Asia/Yangon" timezone handling (UTC fallback + warning).
   • Two daily analysis sessions ............ 12:00 PM  &  04:30 PM.
   • CSV upload ([Date, Time, Result_2D]) with full validation / cleaning,
     or a built-in mock dataset generator (440 records, >= 300 required).
   • 4-section classification of the numbers 00-99:
         Section A: 00-24  |  Section B: 25-49
         Section C: 50-74  |  Section D: 75-99
   • Section probability distribution (%) + Top-5 "Hot Numbers" inside the
     highest-probability section, computed INDEPENDENTLY per session.
   • Live Yangon clock, next-draw countdown, quick result checker,
     interactive tables and a clean, modern dashboard UI.

 Run with:   streamlit run myanmar_2d_app.py

 DISCLAIMER: All predictions are derived from historical frequencies and
 are provided for educational / analytical purposes ONLY. Lottery draws
 are random events — past frequency does NOT guarantee future outcomes.
============================================================================
"""

from __future__ import annotations

import inspect
import io
from datetime import datetime, time as dt_time, timedelta

import numpy as np
import pandas as pd
import pytz
import streamlit as st

# ===========================================================================
# 1. GLOBAL CONFIGURATION & CONSTANTS
# ===========================================================================

TZ_NAME = "Asia/Yangon"                    # Official Myanmar timezone (UTC+6:30)

SESSION_1_LABEL = "12:00 PM"               # Morning draw session
SESSION_2_LABEL = "04:30 PM"               # Evening draw session
SESSION_ORDER: list[str] = [SESSION_1_LABEL, SESSION_2_LABEL]
SESSION_TIMES_24H: dict[str, dt_time] = {
    SESSION_1_LABEL: dt_time(12, 0),
    SESSION_2_LABEL: dt_time(16, 30),
}

REQUIRED_COLUMNS: list[str] = ["Date", "Time", "Result_2D"]

MOCK_DAYS: int = 220        # 220 days x 2 draws/day = 440 mock records (>= 300)
HOT_COUNT: int = 5          # Number of "hot numbers" to display per section
MIN_RECOMMENDED_ROWS: int = 300

WINDOW_OPTIONS: list[str] = ["30", "60", "90", "180", "All"]

# Inclusive (low, high) boundaries for each of the four sections
SECTION_RANGES: dict[str, tuple[int, int]] = {
    "Section A (00-24)": (0, 24),
    "Section B (25-49)": (25, 49),
    "Section C (50-74)": (50, 74),
    "Section D (75-99)": (75, 99),
}
SECTION_EMOJI: dict[str, str] = {
    "Section A (00-24)": "🔵",
    "Section B (25-49)": "🟢",
    "Section C (50-74)": "🟠",
    "Section D (75-99)": "🔴",
}

# Numbers slightly favoured by the mock generator so that the "hot numbers"
# analysis produces meaningful (non-uniform) output out of the box.
MOCK_FAVORITES: dict[str, list[int]] = {
    SESSION_1_LABEL: [12, 23, 38, 45, 57, 72, 81, 96],
    SESSION_2_LABEL: [8, 19, 27, 44, 52, 66, 79, 88],
}

DISCLAIMER: str = (
    "⚠️ **Disclaimer:** All statistics and predictions in this app are derived "
    "purely from **historical frequency data** and are intended for "
    "**educational and analytical purposes only**. Lottery draws are random "
    "events — past frequency does **not** guarantee future results. "
    "Please gamble responsibly."
)

# Streamlit renamed `use_container_width` to `width="stretch"` in v1.49+;
# detect once at import time so the app works on both old and new versions.
_FILL_WIDTH_KWARGS: dict = (
    {"width": "stretch"}
    if "width" in inspect.signature(st.dataframe).parameters
    else {"use_container_width": True}
)


# ===========================================================================
# 2. CORE HELPERS — TIMEZONE, SECTIONS, TIME NORMALISATION
# ===========================================================================

def get_yangon_tz():
    """Safely return the Asia/Yangon timezone, falling back to UTC.

    The fallback protects the app from crashing on systems whose tz database
    is incomplete (e.g. slim Docker images). A warning is raised only once
    per browser session to avoid spamming the UI on every rerun.
    """
    try:
        return pytz.timezone(TZ_NAME)
    except Exception:
        if not st.session_state.get("_tz_warned"):
            st.warning(
                f"Timezone '{TZ_NAME}' is unavailable on this system — "
                "falling back to UTC. All times shown may be offset."
            )
            st.session_state["_tz_warned"] = True
        return pytz.utc


def get_section(number) -> str:
    """Classify a 2D number (00-99) into one of the four sections.

    Accepts ints or strings ('47', ' 7 ', ...) and returns 'Unknown' for
    anything that cannot be interpreted as a number in 0-99.
    """
    try:
        num = int(str(number).strip())
    except (TypeError, ValueError):
        return "Unknown"
    for label, (low, high) in SECTION_RANGES.items():
        if low <= num <= high:
            return label
    return "Unknown"


def normalize_result(raw) -> str | None:
    """Validate a raw draw value and format it as a zero-padded string.

    Handles ints, floats ('42.0' artefacts from Excel exports) and strings.
    Returns None when the value cannot represent a valid 00-99 draw.
    """
    try:
        s = str(raw).strip()
        if s.endswith(".0"):                 # Excel float artefact, e.g. '42.0'
            s = s[:-2]
        num = int(s)
    except (TypeError, ValueError):
        return None
    return f"{num:02d}" if 0 <= num <= 99 else None


def normalize_session(raw_time) -> str | None:
    """Map any reasonable time representation to one of the two canonical
    session labels ('12:00 PM' or '04:30 PM').

    Supported inputs: datetime.time, datetime.datetime, pandas Timestamp,
    '12:00 PM' style strings, 24h strings ('16:30') and compact digits
    ('1230', '930'). Times that do not match exactly are snapped to the
    NEAREST session so slightly-off records (e.g. '12:05 PM') are preserved.
    Returns None when the value cannot be parsed at all.
    """
    try:
        if isinstance(raw_time, dt_time):
            t = raw_time
        elif isinstance(raw_time, (datetime, pd.Timestamp)):
            t = raw_time.time()
        else:
            s = str(raw_time).strip()
            if not s or s.lower() in ("nan", "none", "nat", "-"):
                return None
            if s.endswith(".0"):             # Excel float artefact, e.g. '1230.0'
                s = s[:-2]
            if s.isdigit() and len(s) in (3, 4):     # compact form e.g. '1630'
                hh, mm = int(s[:-2]), int(s[-2:])
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    return None
                t = dt_time(hh, mm)
            else:                            # let pandas parse '12:00 PM' etc.
                t = pd.to_datetime(s).time()

        minutes = t.hour * 60 + t.minute
        s1_min = 12 * 60                     # 12:00 PM in minutes
        s2_min = 16 * 60 + 30                # 04:30 PM in minutes
        # Snap to whichever canonical session is closer
        return (
            SESSION_1_LABEL
            if abs(minutes - s1_min) <= abs(minutes - s2_min)
            else SESSION_2_LABEL
        )
    except Exception:
        return None


def format_countdown(delta: timedelta) -> str:
    """Format a timedelta as a compact 'HHh MMm SSs' string (clamped at zero)."""
    total_seconds = max(int(delta.total_seconds()), 0)
    hours, rem = divmod(total_seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}h {minutes:02d}m {seconds:02d}s"


def get_next_draw(now: datetime, tz) -> tuple[datetime, str]:
    """Return the next upcoming draw as (localized_datetime, session_label).

    Checks today's and tomorrow's two sessions and returns the earliest one
    that is still in the future relative to `now` (Yangon-local time).
    """
    upcoming: list[tuple[datetime, str]] = []
    for offset in (0, 1):                                    # today + tomorrow
        day = (now + timedelta(days=offset)).date()
        for label in SESSION_ORDER:
            draw_dt = tz.localize(datetime.combine(day, SESSION_TIMES_24H[label]))
            if draw_dt > now:
                upcoming.append((draw_dt, label))
    upcoming.sort(key=lambda item: item[0])
    return upcoming[0]


def get_latest_draw(df: pd.DataFrame) -> pd.Series:
    """Return the most recent draw row (Date + session-order aware).

    Lexicographic sorting of '12:00 PM' vs '04:30 PM' is wrong ('0' < '1'),
    so an explicit rank column guarantees correct chronological ordering.
    """
    ranked = df.assign(_rank=df["Time"].map({SESSION_1_LABEL: 0, SESSION_2_LABEL: 1}))
    return ranked.sort_values(["Date", "_rank"]).iloc[-1]


# ===========================================================================
# 3. DATA LAYER — MOCK GENERATOR & CSV VALIDATION PIPELINE
# ===========================================================================

@st.cache_data(show_spinner="Generating mock historical dataset…")
def generate_mock_data(days: int = MOCK_DAYS, seed: int = 42) -> pd.DataFrame:
    """Build a realistic mock historical dataset with >= 300 records.

    Two draws are produced per day (12:00 PM & 04:30 PM). Section picks are
    mildly weighted and each session's 'favourite' numbers get a small boost,
    which makes the analytics engine produce meaningful non-uniform output.
    The RNG seed keeps results deterministic between reruns (cache-friendly).
    """
    rng = np.random.default_rng(seed)
    tz = get_yangon_tz()
    today = datetime.now(tz).date()

    section_labels = list(SECTION_RANGES)
    section_bounds = list(SECTION_RANGES.values())
    # Mild bias towards Sections A/B so distributions are not perfectly flat
    weights = np.array([1.10, 1.05, 0.95, 0.90])
    weights = weights / weights.sum()                        # must sum to 1

    records: list[dict] = []
    for offset in range(days, 0, -1):                        # oldest -> newest
        draw_date = today - timedelta(days=offset)
        date_str = draw_date.strftime("%Y-%m-%d")
        for label in SESSION_ORDER:
            sec_idx = int(rng.choice(len(section_labels), p=weights))
            low, high = section_bounds[sec_idx]
            # 30% of draws come from this session's favourite numbers that
            # also belong to the chosen section (creates visible hot numbers)
            favorites = [n for n in MOCK_FAVORITES[label] if low <= n <= high]
            if favorites and rng.random() < 0.30:
                num = int(rng.choice(favorites))
            else:
                num = int(rng.integers(low, high + 1))
            records.append(
                {"Date": date_str, "Time": label, "Result_2D": f"{num:02d}"}
            )

    df = pd.DataFrame(records)
    df["Section"] = df["Result_2D"].apply(get_section)
    return df.sort_values(["Date", "Time"]).reset_index(drop=True)


def load_csv_data(uploaded_file):
    """Read, validate and clean an uploaded historical CSV file.

    Expected columns: Date | Time | Result_2D

    Pipeline: byte-read → encoding fallbacks → CSV parse → case-insensitive
    column matching → Date/Time/Result normalisation → invalid-row removal →
    duplicate removal → section derivation → chronological sort.

    Returns:
        tuple[pd.DataFrame | None, list[str], list[str]]:
            (clean_dataframe, fatal_errors, non_fatal_warnings).
            `clean_dataframe` is None whenever a fatal error occurred.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # -- 1. Read raw bytes (UploadedFile is a seekable byte stream) ----------
    try:
        uploaded_file.seek(0)
        raw_bytes = uploaded_file.read()
    except Exception as exc:
        return None, [f"Could not read the uploaded file: {exc}"], warnings

    # -- 2. Decode text with progressive encoding fallbacks ------------------
    # Some wrappers (e.g. io.StringIO in tests) already yield str, not bytes
    text: str | None = None
    if isinstance(raw_bytes, str):
        text = raw_bytes
    else:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw_bytes.decode(encoding)
                break
            except (UnicodeDecodeError, AttributeError):
                continue
    if text is None:
        return None, [
            "Unable to decode the file — please re-save it as a UTF-8 CSV."
        ], warnings

    # -- 3. Parse the CSV ----------------------------------------------------
    try:
        df = pd.read_csv(io.StringIO(text))
    except pd.errors.EmptyDataError:
        return None, ["The uploaded CSV is empty (no header row found)."], warnings
    except Exception as exc:
        return None, [f"CSV parsing failed: {exc}"], warnings

    if df.empty:
        return None, ["The CSV has a header but contains no data rows."], warnings

    # -- 4. Match columns case/space-insensitively against requirements ------
    df.columns = [str(col).strip() for col in df.columns]
    lookup = {col.lower(): col for col in df.columns}
    missing = [req for req in REQUIRED_COLUMNS if req.lower() not in lookup]
    if missing:
        return None, [
            f"Missing required column(s): **{', '.join(missing)}**.  \n"
            f"Columns found: `{', '.join(df.columns)}` — expected: "
            f"`{', '.join(REQUIRED_COLUMNS)}`."
        ], warnings
    # Rename matched columns to canonical names and drop any extras
    df = df.rename(columns={lookup[req.lower()]: req for req in REQUIRED_COLUMNS})
    df = df[REQUIRED_COLUMNS].copy()

    # -- 5. Clean the Date column (retry day-first when mostly unparseable) --
    dates_raw = df["Date"].astype(str).str.strip()
    parsed = pd.to_datetime(dates_raw, errors="coerce")
    if parsed.isna().mean() > 0.5:           # maybe format is DD/MM/YYYY etc.
        retry = pd.to_datetime(dates_raw, errors="coerce", dayfirst=True)
        if retry.isna().mean() < parsed.isna().mean():
            parsed = retry
    df["Date"] = parsed.dt.strftime("%Y-%m-%d")              # NaT -> NaN here

    # -- 6. Canonicalise Time into the two supported sessions ----------------
    df["Time"] = df["Time"].apply(normalize_session)

    # -- 7. Validate Result_2D (must be an integer in 00-99) -----------------
    df["Result_2D"] = df["Result_2D"].apply(normalize_result)

    # -- 8. Drop invalid rows and duplicate draws ----------------------------
    invalid = df["Date"].isna() | df["Time"].isna() | df["Result_2D"].isna()
    dropped = int(invalid.sum())
    if dropped:
        warnings.append(
            f"{dropped} row(s) removed — invalid Date, Time or Result_2D value."
        )
    df = df.loc[~invalid].copy()

    before = len(df)
    df = df.drop_duplicates(subset=["Date", "Time"], keep="last")
    duplicates = before - len(df)
    if duplicates:
        warnings.append(
            f"{duplicates} duplicate draw(s) removed (same Date + Time; last kept)."
        )

    if df.empty:
        return None, [
            "No valid records remain after cleaning — nothing to analyse. "
            "Check that Result_2D contains whole numbers 00-99."
        ], warnings

    # -- 9. Derive section labels and sort chronologically -------------------
    df["Section"] = df["Result_2D"].apply(get_section)
    df["_rank"] = df["Time"].map({SESSION_1_LABEL: 0, SESSION_2_LABEL: 1})
    df = (
        df.sort_values(["Date", "_rank"])
        .drop(columns="_rank")
        .reset_index(drop=True)
    )

    if len(df) < MIN_RECOMMENDED_ROWS:
        warnings.append(
            f"Only {len(df)} valid records found — statistics may not be "
            f"reliable ({MIN_RECOMMENDED_ROWS}+ recommended)."
        )
    return df, errors, warnings


def filter_by_window(df: pd.DataFrame, window: str, now: datetime):
    """Restrict the dataframe to the last `window` days ('All' = no filter).

    Falls back to the full dataset when the filtered window would be empty
    (e.g. short uploaded files) and explains why via the returned note.
    """
    if window == "All" or df.empty:
        return df, ""
    cutoff = (now - timedelta(days=int(window))).strftime("%Y-%m-%d")
    window_df = df[df["Date"] >= cutoff]
    if window_df.empty:
        return df, (
            f"The selected {window}-day window contains no records — "
            "showing the full dataset instead."
        )
    return window_df, ""


# ===========================================================================
# 4. ANALYSIS ENGINE — SECTION PROBABILITIES & HOT NUMBERS
# ===========================================================================

def compute_section_probabilities(df: pd.DataFrame, session_label: str):
    """Compute the historical probability (%) of every section for ONE session.

    All four sections are always present in the output (0% if never hit) so
    the UI stays consistent. Returns ({section: pct}, total_draws) and handles
    empty sessions gracefully by returning zeros and total = 0.
    """
    session_df = df[df["Time"] == session_label] if not df.empty else df
    total = int(len(session_df))
    if total == 0:
        return {sec: 0.0 for sec in SECTION_RANGES}, 0
    counts = session_df["Section"].value_counts()
    probabilities = {
        sec: round(float(counts.get(sec, 0)) / total * 100.0, 2)
        for sec in SECTION_RANGES
    }
    return probabilities, total


def get_hot_numbers(
    df: pd.DataFrame, session_label: str, section_label: str, top_n: int = HOT_COUNT
) -> pd.DataFrame:
    """Return the Top-N most frequent numbers inside one section/session.

    Ties are broken by recency (Last_Seen descending). Returns an empty
    (but correctly-shaped) frame when no draws exist for the combination.
    """
    mask = (df["Time"] == session_label) & (df["Section"] == section_label)
    sub = df[mask]
    if sub.empty:
        return pd.DataFrame(columns=["Number", "Hits", "Last_Seen"])
    hot = (
        sub.groupby("Result_2D")
        .agg(Hits=("Result_2D", "size"), Last_Seen=("Date", "max"))
        .sort_values(["Hits", "Last_Seen"], ascending=[False, False])
        .head(top_n)
        .reset_index()
        .rename(columns={"Result_2D": "Number"})
    )
    return hot


# ===========================================================================
# 5. UI COMPONENTS
# ===========================================================================

def inject_custom_css() -> None:
    """Inject small CSS tweaks for rounded metric cards and tighter spacing."""
    st.markdown(
        """
        <style>
            /* Metric cards: subtle translucent background + border */
            div[data-testid="stMetric"] {
                background: rgba(120, 120, 160, 0.08);
                border: 1px solid rgba(120, 120, 160, 0.22);
                border-radius: 10px;
                padding: 14px 16px;
            }
            /* Slightly tighter main-block top padding */
            .block-container { padding-top: 1.2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_clock() -> None:
    """Body of the auto-refreshing sidebar widget: live clock + countdown."""
    tz = get_yangon_tz()
    now = datetime.now(tz)
    next_dt, next_label = get_next_draw(now, tz)
    st.metric(
        "🕐 Yangon Time",
        now.strftime("%I:%M:%S %p"),
        now.strftime("%a, %d %b %Y"),
        delta_color="off",
    )
    st.success(f"Next draw **{next_label}** in **{format_countdown(next_dt - now)}**")


# Auto-refresh the sidebar clock every 5s via fragments when available.
# NOTE: the fragment body must NOT call `with st.sidebar` itself — Streamlit
# requires fragments to be CALLED inside a `with st.sidebar:` block instead
# (main() does exactly that), which also covers the non-fragment fallback.
if hasattr(st, "fragment"):
    @st.fragment(run_every=5)
    def sidebar_live_clock() -> None:
        _render_sidebar_clock()
else:  # pragma: no cover — very old Streamlit fallback (manual refresh only)
    sidebar_live_clock = _render_sidebar_clock


def render_session_panel(probs: dict, total: int, session_label: str) -> None:
    """Render one session's predicted section + probability progress bars."""
    emoji = "☀️" if session_label == SESSION_1_LABEL else "🌆"
    st.markdown(f"##### {emoji} {session_label} Session")
    if total == 0:
        st.warning("No records available for this session in the selected window.")
        return
    best = max(probs, key=probs.get)
    st.success(
        f"Predicted high-probability section: "
        f"{SECTION_EMOJI[best]} **{best}** — {probs[best]:.2f}% historical frequency"
    )
    # Progress bars (value must be a fraction between 0.0 and 1.0)
    for sec, p in probs.items():
        st.progress(min(p, 100.0) / 100.0, text=f"{SECTION_EMOJI[sec]} {sec} — {p:.2f}%")
    st.caption(f"Sample size: {total:,} draw(s) in the selected window.")


def render_hot_numbers_column(df: pd.DataFrame, session_label: str, best_section) -> None:
    """Render the Top-5 hot-number cards for one session's predicted section."""
    emoji = "☀️" if session_label == SESSION_1_LABEL else "🌆"
    if best_section is None:
        st.markdown(f"##### {emoji} {session_label}")
        st.warning("Not enough data to determine a predicted section.")
        return
    st.markdown(
        f"##### {emoji} {session_label} — {SECTION_EMOJI[best_section]} {best_section}"
    )
    hot = get_hot_numbers(df, session_label, best_section)
    if hot.empty:
        st.info("No draws recorded inside this section yet.")
        return
    for _, row in hot.iterrows():
        st.metric(
            f"Number {row['Number']}",
            f"{int(row['Hits'])} hits",
            f"last seen {row['Last_Seen']}",
            delta_color="off",
        )


# ===========================================================================
# 6. MAIN APPLICATION
# ===========================================================================

def main() -> None:
    st.set_page_config(
        page_title="Myanmar 2D — Live Results & Prediction",
        page_icon="🎲",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_custom_css()
    tz = get_yangon_tz()
    now = datetime.now(tz)

    # ------------------------------------------------------------------
    # SIDEBAR — live clock, data source controls, analysis settings
    # ------------------------------------------------------------------
    with st.sidebar:
        st.markdown("## 🎲 Myanmar 2D")
        st.caption("Live Results & Historical Prediction")
        st.divider()

        sidebar_live_clock()                 # fragment: refreshes every 5s

        st.divider()
        st.subheader("⚙️ Data Settings")

        source = st.radio(
            "Data source",
            ["Built-in mock data", "Upload CSV"],
            index=0,
            help="Upload a CSV with columns: Date, Time, Result_2D.",
        )

        analysis_df: pd.DataFrame | None = None
        source_label = "Built-in mock data"

        if source == "Upload CSV":
            uploaded = st.file_uploader(
                "Historical CSV [Date, Time, Result_2D]",
                type=["csv"],
                accept_multiple_files=False,
            )
            if uploaded is not None:
                analysis_df, errors, csv_warnings = load_csv_data(uploaded)
                for msg in errors:                       # fatal problems
                    st.error(msg)
                for msg in csv_warnings:                 # non-fatal notices
                    st.warning(msg)
                if analysis_df is not None:
                    source_label = f"CSV · {uploaded.name}"
                    st.success(f"Loaded {len(analysis_df):,} valid record(s).")
                else:
                    st.info("↩️ Falling back to built-in mock data.")
            else:
                st.info("Upload a CSV file, or switch back to mock data.")

        # Fallback chain: upload failure / no file -> built-in mock dataset
        if analysis_df is None:
            analysis_df = generate_mock_data()

        st.divider()
        window = st.select_slider(
            "Analysis window (days)",
            options=WINDOW_OPTIONS,
            value="90",
            help="Statistics are computed only from draws within this window.",
        )
        if st.button("🔄 Refresh analysis", **_FILL_WIDTH_KWARGS):
            st.rerun()

        st.divider()
        with st.expander("ℹ️ How the analysis works"):
            st.markdown(
                """
                1. Every historical draw is classified into one of **4 sections**:
                   A: 00-24, B: 25-49, C: 50-74, D: 75-99.
                2. For each session (12:00 PM / 04:30 PM) we compute the
                   **percentage of past draws** that fell into every section.
                3. The section with the highest historical frequency is
                   highlighted as the *statistical favourite*.
                4. Inside that favourite section the **Top-5 most frequently
                   drawn numbers** are listed as *hot numbers*.
                """
            )
        st.caption(DISCLAIMER)

    # ------------------------------------------------------------------
    # DATA PREPARATION — apply the selected analysis window
    # ------------------------------------------------------------------
    window_df, window_note = filter_by_window(analysis_df, window, now)
    if window_note:
        st.warning(window_note)

    # Pre-compute probabilities / best sections ONCE for both sessions
    probs_by_session: dict[str, dict] = {}
    totals_by_session: dict[str, int] = {}
    best_by_session: dict[str, str | None] = {}
    for session in SESSION_ORDER:
        probs, total = compute_section_probabilities(window_df, session)
        probs_by_session[session] = probs
        totals_by_session[session] = total
        best_by_session[session] = max(probs, key=probs.get) if total else None

    # ------------------------------------------------------------------
    # MAIN HEADER — title, live banner, KPI metric cards
    # ------------------------------------------------------------------
    st.title("🎲 Myanmar 2D — Live Results & Historical Prediction")
    st.caption(
        f"Timezone: **Asia/Yangon** · Sessions: **12:00 PM** & **04:30 PM** · "
        f"Records: **{len(analysis_df):,}** · Source: **{source_label}**"
    )

    next_dt, next_label = get_next_draw(now, tz)
    st.success(
        f"🟢 **LIVE** — Next draw: **{next_label}** in "
        f"**{format_countdown(next_dt - now)}** "
        f"(Yangon: {now.strftime('%Y-%m-%d %I:%M:%S %p')})"
    )

    latest = get_latest_draw(window_df)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📅 Today (Yangon)", now.strftime("%d %b %Y"), now.strftime("%A"), delta_color="off")
    m2.metric("⏭️ Next Draw", next_label, format_countdown(next_dt - now), delta_color="off")
    m3.metric(
        "🗂️ Records Analyzed",
        f"{len(window_df):,}",
        f"{window_df['Date'].nunique()} days",
        delta_color="off",
    )
    m4.metric(
        "🀄 Latest Result",
        str(latest["Result_2D"]),
        f"{latest['Date']} · {latest['Time']}",
        delta_color="off",
    )

    # ------------------------------------------------------------------
    # SECTION PROBABILITY PREDICTION (both sessions side-by-side)
    # ------------------------------------------------------------------
    st.markdown("#### 🎯 Section Probability Prediction")
    panel_morning, panel_evening = st.columns(2)
    with panel_morning:
        render_session_panel(
            probs_by_session[SESSION_1_LABEL], totals_by_session[SESSION_1_LABEL],
            SESSION_1_LABEL,
        )
    with panel_evening:
        render_session_panel(
            probs_by_session[SESSION_2_LABEL], totals_by_session[SESSION_2_LABEL],
            SESSION_2_LABEL,
        )

    # ------------------------------------------------------------------
    # HOT NUMBERS (Top-5 inside each session's predicted section)
    # ------------------------------------------------------------------
    st.markdown("#### 🔥 Hot Numbers — Top 5 in Predicted Section")
    hot_morning, hot_evening = st.columns(2)
    with hot_morning:
        render_hot_numbers_column(window_df, SESSION_1_LABEL, best_by_session[SESSION_1_LABEL])
    with hot_evening:
        render_hot_numbers_column(window_df, SESSION_2_LABEL, best_by_session[SESSION_2_LABEL])

    # ------------------------------------------------------------------
    # QUICK RESULT CHECKER — test any number against current predictions
    # ------------------------------------------------------------------
    with st.expander("🔎 Quick Result Checker — test a number against the prediction"):
        raw_value = st.text_input(
            "Enter a 2D number (00-99)", max_chars=3, placeholder="e.g. 47"
        )
        if raw_value.strip():
            normalized = normalize_result(raw_value)
            if normalized is None:
                st.error("Invalid input — please enter a whole number between 00 and 99.")
            else:
                section = get_section(normalized)
                st.info(
                    f"**{normalized}** belongs to "
                    f"{SECTION_EMOJI.get(section, '⚪')} **{section}**"
                )
                comparison_rows = []
                for session in SESSION_ORDER:
                    best = best_by_session[session]
                    hot = get_hot_numbers(window_df, session, best) if best else pd.DataFrame()
                    in_hot = (not hot.empty) and normalized in set(hot["Number"])
                    comparison_rows.append({
                        "Session": session,
                        "Predicted Section": best or "N/A",
                        "Your Number's Section": section,
                        "Matches Prediction": "✅ Yes" if section == best else "❌ No",
                        "In Hot List": "🔥 Yes" if in_hot else "—",
                    })
                st.dataframe(
                    pd.DataFrame(comparison_rows),
                    hide_index=True,
                    **_FILL_WIDTH_KWARGS,
                )

    # ------------------------------------------------------------------
    # DETAIL TABS — analysis charts, history, data export
    # ------------------------------------------------------------------
    st.markdown("---")
    tab_analysis, tab_history, tab_data = st.tabs(
        ["📊 Section Analysis", "🗂️ Historical Results", "📥 Data & Export"]
    )

    # ----- Tab 1: comparative section analysis --------------------------
    with tab_analysis:
        chart = pd.DataFrame(probs_by_session)      # rows=sections, cols=sessions
        chart.index = list(SECTION_RANGES.keys())
        st.bar_chart(chart)
        st.caption(
            "Section distribution (%) per session across the selected window. "
            "The tallest bar marks each session's statistical favourite."
        )
        table_m, table_e = st.columns(2)
        for col, session in ((table_m, SESSION_1_LABEL), (table_e, SESSION_2_LABEL)):
            sub = window_df[window_df["Time"] == session]
            with col:
                emoji = "☀️" if session == SESSION_1_LABEL else "🌆"
                st.markdown(f"##### {emoji} {session}")
                if sub.empty:
                    st.warning("No records for this session.")
                    continue
                counts = sub["Section"].value_counts()
                detail = pd.DataFrame({
                    "Section": list(SECTION_RANGES.keys()),
                    "Draws": [int(counts.get(sec, 0)) for sec in SECTION_RANGES],
                })
                detail["Probability %"] = (detail["Draws"] / len(sub) * 100).round(2)
                st.dataframe(detail, hide_index=True, **_FILL_WIDTH_KWARGS)

    # ----- Tab 2: recent historical results ------------------------------
    with tab_history:
        recent_n = st.slider("Rows to display", 10, 200, 25, step=5)
        recent = window_df.tail(recent_n).iloc[::-1]        # newest first
        st.dataframe(recent, hide_index=True, **_FILL_WIDTH_KWARGS)
        sum_m, sum_e = st.columns(2)
        for col, session in ((sum_m, SESSION_1_LABEL), (sum_e, SESSION_2_LABEL)):
            sub = window_df[window_df["Time"] == session]
            with col:
                emoji = "☀️" if session == SESSION_1_LABEL else "🌆"
                st.markdown(f"##### {emoji} {session} summary")
                if sub.empty:
                    st.warning("No data for this session.")
                    continue
                top_sec = sub["Section"].value_counts().idxmax()
                top_num = sub["Result_2D"].value_counts().idxmax()
                st.metric("Draws", f"{len(sub):,}", delta_color="off")
                st.metric(
                    "Most frequent section",
                    f"{SECTION_EMOJI[top_sec]} {top_sec}",
                    delta_color="off",
                )
                st.metric("Most frequent number", str(top_num), delta_color="off")

    # ----- Tab 3: full dataset preview + export --------------------------
    with tab_data:
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Total rows", f"{len(analysis_df):,}", delta_color="off")
        d2.metric("Days covered", f"{analysis_df['Date'].nunique():,}", delta_color="off")
        d3.metric(
            "First draw",
            analysis_df["Date"].min(),
            delta_color="off",
        )
        d4.metric(
            "Last draw",
            analysis_df["Date"].max(),
            delta_color="off",
        )
        split = analysis_df["Time"].value_counts()
        st.caption(
            f"Session split — ☀️ {SESSION_1_LABEL}: **{int(split.get(SESSION_1_LABEL, 0)):,}** "
            f"· 🌆 {SESSION_2_LABEL}: **{int(split.get(SESSION_2_LABEL, 0)):,}**"
        )
        st.dataframe(analysis_df, height=400, hide_index=True, **_FILL_WIDTH_KWARGS)
        st.download_button(
            "⬇️ Download cleaned dataset as CSV",
            data=analysis_df.to_csv(index=False).encode("utf-8"),
            file_name="myanmar_2d_clean.csv",
            mime="text/csv",
            **_FILL_WIDTH_KWARGS,
        )

    # ------------------------------------------------------------------
    # FOOTER — mandatory disclaimer
    # ------------------------------------------------------------------
    st.markdown("---")
    st.warning(DISCLAIMER)
    st.caption("Built with Streamlit · Asia/Yangon timezone · For educational use only.")


if __name__ == "__main__":
    main()
