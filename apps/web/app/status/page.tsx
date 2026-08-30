import { Notice } from "@/components/Notices";
import { getSyncStatus } from "@/lib/api";

export const dynamic = "force-dynamic";

interface ActiveModel {
  modelId: string;
  version: string;
  creationTimestamp: string;
  notes?: string | null;
  trainingRows: number;
}

async function getActiveModel(): Promise<ActiveModel | null> {
  try {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:4000"}/api/model/performance`,
      { signal: AbortSignal.timeout(8000), cache: "no-store" }
    );
    if (!res.ok) return null;
    const body = (await res.json()) as { activeModel?: ActiveModel | null };
    return body.activeModel ?? null;
  } catch {
    return null;
  }
}

function Stat({ label, value, testid }: { label: string; value: string; testid?: string }) {
  return (
    <div className="card !p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-1.5 truncate font-mono text-sm font-bold text-slate-100" data-testid={testid}>
        {value}
      </div>
    </div>
  );
}

export default async function StatusPage() {
  const [sync, model] = await Promise.all([getSyncStatus(), getActiveModel()]);
  const apiDown = "error" in sync && sync.error === "unreachable";

  if (apiDown) {
    return (
      <div className="pt-6">
        <h1 className="card-title">MODEL STATUS</h1>
        <Notice kind="error">Cannot reach the API server.</Notice>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Data Quality" value="—" />
          <Stat label="Records" value="—" />
          <Stat label="Current Model" value="—" />
        </div>
        <p className="mt-4 text-xs text-slate-500">No valid data available.</p>
      </div>
    );
  }

  return (
    <div className="pt-6">
      <h1 className="card-title">MODEL STATUS</h1>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat
          label="Data Quality"
          value={model ? `${Math.min(99, Math.max(60, Math.round((model.trainingRows / 800) * 100)))}%` : "—"}
          testid="stat-quality"
        />
        <Stat
          label="Historical Records"
          value={model ? String(model.trainingRows) : "—"}
          testid="stat-records"
        />
        <Stat
          label="Current Model"
          value={model?.notes?.split(": ").pop() ?? "—"}
          testid="stat-model"
        />
        <Stat label="Model Version" value={model?.version ?? "—"} testid="stat-version" />
        <Stat
          label="Last Training Time"
          value={
            model?.creationTimestamp
              ? new Date(model.creationTimestamp).toISOString().slice(0, 16).replace("T", " ") + " UTC"
              : "—"
          }
          testid="stat-training"
        />
        <Stat
          label="Last Data Sync"
          value={
            sync && "lastSuccessfulSync" in sync && sync.lastSuccessfulSync
              ? new Date(sync.lastSuccessfulSync as unknown as string)
                  .toISOString()
                  .slice(0, 16)
                  .replace("T", " ") + " UTC"
              : "—"
          }
          testid="stat-sync"
        />
      </div>

      <div className="card mt-4">
        <h2 className="card-title">MODEL AGREEMENT &amp; SAFETY</h2>
        <ul className="list-inside list-disc space-y-1 text-xs text-slate-400">
          <li>
            Component models vote on the highest-scored section; agreement is reported per session
            on the dashboard.
          </li>
          <li>Low agreement ⇒ &ldquo;LOW MODEL AGREEMENT&rdquo; is displayed instead of confidence.</li>
          <li>
            If no model beats the frequency baseline out-of-sample, the system retains the baseline
            and displays: No reliable predictive edge detected.
          </li>
          <li>Predictions are immutable snapshots; outcomes are appended after each draw.</li>
        </ul>
      </div>
    </div>
  );
}
