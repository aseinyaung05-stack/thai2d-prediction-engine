import { Notice } from "@/components/Notices";
import { getBacktests, type BacktestRow } from "@/lib/api";

export const dynamic = "force-dynamic";

function pct(v?: number): string {
  return typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—";
}

function MetricsTable({ rows }: { rows: BacktestRow[] }) {
  return (
    <div className="card overflow-x-auto">
      <table className="w-full text-xs" data-testid="backtest-table">
        <thead>
          <tr className="border-b border-ink-700 text-left text-[10px] uppercase tracking-wider text-slate-500">
            <th className="py-2 pr-3">Model</th>
            <th className="py-2 pr-3">Version</th>
            <th className="py-2 pr-3">N</th>
            <th className="py-2 pr-3">Top-1</th>
            <th className="py-2 pr-3">Top-5</th>
            <th className="py-2 pr-3">Top-10</th>
            <th className="py-2 pr-3">Section Acc</th>
            <th className="py-2 pr-3">Log Loss</th>
            <th className="py-2">Brier</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr
              key={b.id}
              className={`border-b border-ink-850 last:border-0 ${
                b.isProduction ? "bg-accent-green/5" : ""
              }`}
            >
              <td className="py-2 pr-3 font-semibold text-slate-200">
                {b.modelName}
                {b.isProduction && (
                  <span className="badge ml-2 bg-accent-green/15 text-accent-green">PROD</span>
                )}
              </td>
              <td className="py-2 pr-3 font-mono text-[11px] text-slate-400">{b.modelVersion}</td>
              <td className="py-2 pr-3 font-mono text-slate-500">{b.nPredictions}</td>
              <td className="py-2 pr-3 font-mono">{pct(b.metrics.top1_hit_rate)}</td>
              <td className="py-2 pr-3 font-mono">{pct(b.metrics.top5_hit_rate)}</td>
              <td className="py-2 pr-3 font-mono">{pct(b.metrics.top10_hit_rate)}</td>
              <td className="py-2 pr-3 font-mono">{pct(b.metrics.section_accuracy)}</td>
              <td className="py-2 pr-3 font-mono">{b.metrics.log_loss?.toFixed(4) ?? "—"}</td>
              <td className="py-2 font-mono">{b.metrics.brier_score?.toFixed(4) ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function BacktestPage() {
  const data = await getBacktests();
  const rows = "backtests" in data ? (data.backtests ?? []) : [];
  const prod = rows.find((r) => r.isProduction);
  const baseline = rows.find((r) => r.modelName === "frequency");

  const edgeBeatsBaseline =
    prod && baseline && prod.metrics.log_loss != null && baseline.metrics.log_loss != null
      ? prod.metrics.log_loss < baseline.metrics.log_loss
      : null;

  return (
    <div className="pt-6">
      <h1 className="card-title">BACKTEST PERFORMANCE — WALK-FORWARD OUT-OF-SAMPLE</h1>

      {"error" in data && data.error && (
        <Notice kind="error">Cannot reach the API server. Run the engine backtest first.</Notice>
      )}
      {rows.length === 0 && !("error" in data && data.error) && (
        <Notice kind="warn">No valid data available.</Notice>
      )}

      {rows.length > 0 && (
        <>
          {prod && (
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {(
                [
                  ["Top-1", pct(prod.metrics.top1_hit_rate)],
                  ["Top-5", pct(prod.metrics.top5_hit_rate)],
                  ["Top-10", pct(prod.metrics.top10_hit_rate)],
                  ["Section Acc", pct(prod.metrics.section_accuracy)],
                  ["Log Loss", prod.metrics.log_loss?.toFixed(4) ?? "—"],
                  ["Brier", prod.metrics.brier_score?.toFixed(4) ?? "—"],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="card !p-3 text-center">
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">{k}</div>
                  <div className="mt-1 font-mono text-sm font-bold text-slate-100" data-testid={`metric-${k}`}>
                    {v}
                  </div>
                </div>
              ))}
            </div>
          )}

          <MetricsTable rows={rows} />

          <div className="card mt-4" data-testid="baseline-comparison">
            <h2 className="card-title">BASELINE vs PRODUCTION MODEL</h2>
            {edgeBeatsBaseline === null ? (
              <p className="text-xs text-slate-400">
                Baseline comparison unavailable — run a full walk-forward evaluation.
              </p>
            ) : edgeBeatsBaseline ? (
              <p className="text-xs text-accent-green">
                Production model outperformed the frequency baseline out-of-sample in this
                evaluation window. Sample size: {prod?.nPredictions} predictions.
              </p>
            ) : (
              <p className="text-xs font-semibold text-amber-300">
                No reliable predictive edge detected.
              </p>
            )}
            <p className="mt-2 text-[10px] italic text-slate-600">
              Random-chance references: Top-1 = 1.0%, Top-10 = 10%, uniform log loss ={" "}
              {rows[0]?.metrics.uniform_log_loss_reference ?? 4.6052}.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
