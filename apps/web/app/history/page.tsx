import { Notice } from "@/components/Notices";
import { getHistory } from "@/lib/api";

export const dynamic = "force-dynamic";

function fmtUtc(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export default async function HistoryPage() {
  const data = await getHistory(60);
  const rows = "results" in data ? data.results ?? [] : [];

  return (
    <div className="pt-6">
      <h1 className="card-title">LATEST RESULTS ? HISTORICAL DATA</h1>

      {"error" in data && data.error && (
        <Notice kind="error">
          API error: Historical data unavailable right now.
        </Notice>
      )}
      {rows.length === 0 && !("error" in data && data.error) && (
        <Notice kind="warn">No valid data available.</Notice>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full text-xs" data-testid="history-table">
          <thead>
            <tr className="border-b border-ink-700 text-left text-[10px] uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-4">Date (MM)</th>
              <th className="py-2 pr-4">Session</th>
              <th className="py-2 pr-4">2D</th>
              <th className="py-2 pr-4">SET</th>
              <th className="py-2 pr-4">Source</th>
              <th className="py-2">Time (UTC)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.date}-${r.session}-${i}`} className="border-b border-ink-850 last:border-0">
                <td className="py-2 pr-4 font-mono">{r.date}</td>
                <td className="py-2 pr-4">
                  <span
                    className={`badge ${
                      r.session === "MORNING"
                        ? "bg-accent-blue/15 text-accent-blue"
                        : "bg-accent-violet/15 text-accent-violet"
                    }`}
                  >
                    {r.session === "MORNING" ? "12:00 PM" : "4:30 PM"}
                  </span>
                </td>
                <td className="py-2 pr-2">
                  <span className="num-chip !h-7 !w-10">{r.twod}</span>
                </td>
                <td className="py-2 pr-4 font-mono text-slate-400">
                  {r.setValue != null ? r.setValue.toLocaleString() : "?"}
                </td>
                <td className="py-2 pr-4 text-slate-500">{r.source}</td>
                <td className="py-2 font-mono text-slate-500">{fmtUtc(r.sourceTimestamp)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-[10px] text-slate-600">
          Source timestamps are stored in UTC; user-facing sessions are Asia/Yangon.
        </p>
      </div>
    </div>
  );
}


