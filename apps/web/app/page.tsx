import CountdownMM from "@/components/CountdownMM";
import SectionBars from "@/components/SectionBars";
import { Notice } from "@/components/Notices";
import { getToday, type SessionPrediction } from "@/lib/api";

export const dynamic = "force-dynamic";

const SECTION_LABELS: Record<string, string> = {
  A: "A: 00–24",
  B: "B: 25–49",
  C: "C: 50–74",
  D: "D: 75–99",
};

function SessionCard({
  name,
  data,
}: {
  name: string;
  data?: SessionPrediction | { error: string; stale?: boolean };
}) {
  const sp = data as SessionPrediction;
  const sections = sp?.section_scores ?? [];
  const top = sp?.top10 ?? [];
  const headline = sp?.view?.headline;

  return (
    <section className="card" data-testid={`session-${name.includes("12") ? "morning" : "afternoon"}`}>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold text-slate-100">{name}</h2>
        {sp?.stale ? (
          <span className="badge bg-accent-amber/15 text-accent-amber">CACHED</span>
        ) : (
          <span className="badge bg-accent-green/15 text-accent-green">LIVE</span>
        )}
      </div>

      {!sp || sp.error ? (
        <p className="text-xs text-slate-500">{sp?.error ?? "No valid data available."}</p>
      ) : (
        <>
          <dl className="mb-4 space-y-1 text-xs">
            <div className="flex justify-between">
              <dt className="text-slate-400">Highest Model-Scored Section</dt>
              <dd
                className="font-bold"
                data-testid="highest-section"
              >
                {headline?.highest_model_scored_section ?? "—"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-400">Top Candidates</dt>
              <dd className="font-mono font-semibold text-slate-100">
                {(headline?.top_candidates ?? []).join(" ") || "—"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-400">Model Agreement</dt>
              <dd>{sp.view?.model_agreement ?? "—"}</dd>
            </div>
          </dl>

          {sections.length > 0 && (
            <>
              <SectionBars
                data={sections.map((s) => ({
                  section: s.section,
                  probability: s.probability,
                }))}
              />
              <ul className="mt-3 space-y-1 text-[11px] text-slate-400">
                {[...sections]
                  .sort((a, b) => a.rank - b.rank)
                  .map((s) => (
                    <li key={s.section} className="flex items-center gap-2">
                      <span
                        className="inline-block h-2 w-2 rounded-full"
                        style={{
                          backgroundColor: {
                            A: "#3b82f6",
                            B: "#22c55e",
                            C: "#f59e0b",
                            D: "#ef4444",
                          }[s.section],
                        }}
                      />
                      <span className="w-24">{SECTION_LABELS[s.section]}</span>
                      <span className="font-mono">{(s.probability * 100).toFixed(1)}%</span>
                    </li>
                  ))}
              </ul>
              {!sp.view?.edge_detected && (
                <p className="mt-3 rounded-md border border-accent-amber/30 bg-accent-amber/10 px-3 py-2 text-[11px] text-amber-200">
                  {sp.view?.edge_notice ?? "No reliable predictive edge detected."}
                </p>
              )}
              <p className="mt-2 text-[10px] italic text-slate-500">
                {headline?.wording_note}
              </p>
            </>
          )}

          {top.length > 0 && (
            <table className="mt-4 w-full text-xs" data-testid="top-table">
              <thead>
                <tr className="border-b border-ink-700 text-left text-[10px] uppercase tracking-wider text-slate-500">
                  <th className="py-1.5 pr-2">#</th>
                  <th className="py-1.5 pr-2">Number</th>
                  <th className="py-1.5 pr-2">Section</th>
                  <th className="py-1.5 text-right">Model Score</th>
                </tr>
              </thead>
              <tbody>
                {top.slice(0, 10).map((n) => (
                  <tr key={n.number} className="border-b border-ink-850 last:border-0">
                    <td className="py-1.5 pr-2 font-mono text-slate-500">{n.rank}</td>
                    <td className="py-1.5 pr-2">
                      <span className="num-chip">{String(n.number).padStart(2, "0")}</span>
                    </td>
                    <td className="py-1.5 pr-2 font-semibold text-slate-300">
                      SECTION {n.section}
                    </td>
                    <td className="py-1.5 text-right font-mono text-accent-green">
                      {(
                        (n.calibrated_probability ?? n.score ?? 0) * 100
                      ).toFixed(2)}
                      %
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

export default async function DashboardPage() {
  const today = await getToday();
  const ok = "sessions" in today;

  return (
    <div className="pt-6" data-testid="dashboard-root">
      {/* §45 headline block */}
      <div className="card mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-base font-extrabold tracking-wide text-slate-50 sm:text-lg">
            TODAY&apos;S THAI 2D MODEL ANALYSIS
          </h1>
          <p className="mt-0.5 text-[11px] text-slate-500">
            {"date" in today ? today.date : ""} • Asia/Yangon • estimates only — not guarantees
          </p>
        </div>
        <CountdownMM />
      </div>

      {!ok && <Notice kind="error">API server unreachable — cannot reach the API server.</Notice>}
      {ok && today.notice && <Notice kind="warn">{today.notice}</Notice>}

      <div className="grid gap-5 lg:grid-cols-2" data-testid="sessions-grid">
        <SessionCard
          name="12:00 PM SESSION"
          data={ok ? today.sessions?.["MORNING"] : undefined}
        />
        <SessionCard
          name="4:30 PM SESSION"
          data={ok ? today.sessions?.["AFTERNOON"] : undefined}
        />
      </div>

      <p className="mt-6 text-center text-[11px] text-slate-600">
        DATA → FEATURES → MODEL → 00–99 SCORES → FOUR SECTIONS → BACKTEST → DASHBOARD
      </p>
    </div>
  );
}
