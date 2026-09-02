"use client";

import { useEffect, useState } from "react";
import { getMonthlyPerformance, type MonthlyPerformance } from "@/lib/api";

function Pct({ value, benchmark }: { value: number | null; benchmark: number }) {
  if (value === null) return <span className="font-mono text-sm text-slate-400">—</span>;
  const above = value >= benchmark;
  return (
    <span
      className={`font-mono text-sm font-bold ${above ? "text-accent-green" : "text-amber-300"}`}
      title={`Random chance benchmark: ${benchmark}%`}
    >
      {value.toFixed(1)}%
    </span>
  );
}

export default function MonthlyPerformance() {
  const [data, setData] = useState<MonthlyPerformance | null>(null);
  const [failed, setFailed] = useState(false);
  const [showDetail, setShowDetail] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMonthlyPerformance().then((d) => {
      if (cancelled) return;
      if ("error" in d) setFailed(true);
      else setData(d);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) return null; // quietly hide the card when API is down
  if (!data) {
    return (
      <section className="card mt-5">
        <h2 className="card-title">MONTHLY PERFORMANCE — SECTION HIT %</h2>
        <p className="text-xs text-slate-500">Loading…</p>
      </section>
    );
  }

  const aboveChance =
    data.section_hit_pct !== null && data.section_hit_pct >= data.chance_benchmark.section_pct;
  const sessLabel: Record<string, string> = { MORNING: "12:00 PM", AFTERNOON: "4:30 PM" };

  return (
    <section className="card mt-5" data-testid="monthly-performance">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="card-title !mb-0">
          MONTHLY PERFORMANCE — SECTION HIT % ({data.month})
        </h2>
        <span className="badge bg-ink-800 text-slate-400">{data.graded} graded</span>
      </div>

      {data.graded === 0 ? (
        <p className="text-xs text-slate-500">
          No graded predictions yet this month. Outcomes are attached automatically after each
          draw&apos;s result is published.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-lg border border-ink-700 bg-ink-850 p-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">Section Hit %</div>
              <div className="mt-1 font-mono text-xl font-extrabold text-slate-50" data-testid="section-hit-pct">
                {data.section_hit_pct?.toFixed(1) ?? "—"}%
              </div>
              <div className="mt-0.5 text-[10px] text-slate-500">
                {data.section_hits}/{data.graded} graded
              </div>
            </div>
            <div className="rounded-lg border border-ink-700 bg-ink-850 p-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">Top-10 Hit %</div>
              <Pct value={data.top10_pct} benchmark={data.chance_benchmark.top10_pct} />
              <div className="mt-0.5 text-[10px] text-slate-500">
                {data.top10_hits}/{data.graded}
              </div>
            </div>
            <div className="rounded-lg border border-ink-700 bg-ink-850 p-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">Top-1 (exact)</div>
              <Pct value={data.top1_pct} benchmark={data.chance_benchmark.top1_pct} />
              <div className="mt-0.5 text-[10px] text-slate-500">
                {data.top1_hits}/{data.graded}
              </div>
            </div>
            <div className="rounded-lg border border-ink-700 bg-ink-850 p-3 text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">Chance</div>
              <div className="mt-1 font-mono text-sm text-slate-400">
                25% / 10% / 1%
              </div>
              <div className="mt-0.5 text-[10px] text-slate-600">section / top-10 / top-1</div>
            </div>
          </div>

          <div
            className={`mt-3 rounded-md border px-3 py-2 text-[11px] ${
              aboveChance
                ? "border-accent-green/30 bg-accent-green/10 text-green-200"
                : "border-accent-amber/30 bg-accent-amber/10 text-amber-200"
            }`}
          >
            {aboveChance
              ? `Section hit rate ${data.section_hit_pct}% is currently at or above the 25% random-chance benchmark.`
              : `Section hit rate ${data.section_hit_pct ?? "—"}% is currently below the 25% random-chance benchmark — consistent with the honest no-edge verdict.`}
            {" "}Small samples are noisy; judge only after ~20+ graded draws.
          </div>

          <div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
            {Object.entries(data.by_session).map(([sess, s]) => (
              <div key={sess} className="flex items-center justify-between rounded-md bg-ink-800 px-3 py-2">
                <span className="text-slate-400">{sessLabel[sess] ?? sess}</span>
                <span className="font-mono text-slate-200">
                  {s.graded > 0
                    ? `${s.section_hits}/${s.graded} sections (${((s.section_hits / s.graded) * 100).toFixed(0)}%)`
                    : "no graded draws"}
                </span>
              </div>
            ))}
          </div>

          <button
            onClick={() => setShowDetail(!showDetail)}
            className="mt-3 text-[11px] font-medium text-accent-blue hover:underline"
          >
            {showDetail ? "Hide" : "Show"} draw-by-draw detail
          </button>

          {showDetail && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-ink-700 text-left text-[10px] uppercase tracking-wider text-slate-500">
                    <th className="py-1.5 pr-3">Date</th>
                    <th className="py-1.5 pr-3">Session</th>
                    <th className="py-1.5 pr-3">Predicted</th>
                    <th className="py-1.5 pr-3">Actual</th>
                    <th className="py-1.5 pr-3">Section</th>
                    <th className="py-1.5 pr-3">Rank</th>
                    <th className="py-1.5">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {data.detail.map((d, i) => (
                    <tr key={i} className="border-b border-ink-850 last:border-0">
                      <td className="py-1.5 pr-3 font-mono">{String(d.date).slice(0, 10)}</td>
                      <td className="py-1.5 pr-3">{sessLabel[d.session] ?? d.session}</td>
                      <td className="py-1.5 pr-3 font-semibold">SECTION {d.predicted_section}</td>
                      <td className="py-1.5 pr-3">
                        <span className="num-chip !h-6 !w-9">{d.actual_result}</span>
                      </td>
                      <td className="py-1.5 pr-3">{d.actual_section}</td>
                      <td className="py-1.5 pr-3 font-mono">{d.actual_rank ?? "—"}</td>
                      <td className="py-1.5">
                        {d.section_hit ? (
                          <span className="badge bg-accent-green/15 text-accent-green">HIT</span>
                        ) : (
                          <span className="badge bg-accent-red/15 text-accent-red">MISS</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="mt-3 text-[10px] italic text-slate-600">{data.disclaimer}</p>
        </>
      )}
    </section>
  );
}
