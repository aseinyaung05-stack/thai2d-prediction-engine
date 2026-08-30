"use client";

import { useEffect, useState } from "react";

/** Countdown to the next REAL draw (12:00 PM / 4:30 PM, Asia/Yangon).
 *  Weekend-aware: Thai SET is closed Sat/Sun, so on weekends this counts
 *  down to Monday 12:00 PM Yangon. */
export default function CountdownMM() {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  function nextDraw(nowMs: number): { label: string; atEpochMs: number; weekend: boolean } {
    // Yangon wall-clock parts of "now" via IANA zone.
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Yangon",
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).formatToParts(new Date(nowMs));
    const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
    const y = parseInt(get("year"), 10);
    const mo = parseInt(get("month"), 10);
    const d = parseInt(get("day"), 10);
    const wd = get("weekday"); // Sun..Sat

    // Yangon is a fixed UTC+06:30 zone: 12:00 Yangon = 05:30 UTC,
    // 16:30 Yangon = 10:00 UTC. Anchor candidates to absolute epochs.
    const baseDayUtc = Date.UTC(y, mo - 1, d);
    const dayIndex: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
    const dow = dayIndex[wd] ?? new Date(baseDayUtc).getUTCDay();

    const draws = [
      { label: "12:00 PM", utcOffsetMs: 5.5 * 3600_000 },
      { label: "4:30 PM", utcOffsetMs: 10 * 3600_000 },
    ];

    let weekend = dow === 0 || dow === 6;
    let best: { label: string; atEpochMs: number } | null = null;
    for (let add = 0; add <= 7 && !best; add++) {
      const day = baseDayUtc + add * 86_400_000;
      const ddow = new Date(day).getUTCDay();
      if (ddow === 0 || ddow === 6) continue; // skip Sat/Sun
      for (const draw of draws) {
        const epoch = day + draw.utcOffsetMs;
        if (epoch > nowMs) {
          best = { label: draw.label, atEpochMs: epoch };
          break;
        }
      }
    }
    if (!best) best = { label: "12:00 PM", atEpochMs: baseDayUtc + 8 * 86_400_000 + 5.5 * 3600_000 };
    return { ...best, weekend };
  }

  if (now === null) return <div className="h-5" />;

  const { label, atEpochMs, weekend } = nextDraw(now);
  const ms = Math.max(0, atEpochMs - now);
  const days = Math.floor(ms / 86_400_000);
  const h = Math.floor((ms % 86_400_000) / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);

  return (
    <div className="font-mono text-sm text-slate-300" data-testid="countdown">
      <span className="mr-2 rounded bg-accent-violet/20 px-2 py-0.5 text-[11px] font-semibold text-accent-violet">
        {label} MM
      </span>
      {days > 0 && <span className="mr-1 text-slate-400">{days}d</span>}
      {String(h).padStart(2, "0")}:{String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
      {weekend && (
        <span className="ml-2 rounded bg-accent-amber/15 px-1.5 py-0.5 text-[10px] text-accent-amber">
          SET closed — next trading day
        </span>
      )}
    </div>
  );
}
