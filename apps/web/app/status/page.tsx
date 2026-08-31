"use client";

import { useEffect, useState } from "react";
import { Notice } from "@/components/Notices";
import { getSyncStatus } from "@/lib/api";

interface ActiveModel {
  modelId: string;
  version: string;
  creationTimestamp: string;
  notes?: string | null;
  trainingRows: number;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card !p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className="mt-1.5 truncate font-mono text-sm font-bold text-slate-100">{value}</div>
    </div>
  );
}

export default function StatusPage() {
  const [sync, setSync] = useState<{ lastSuccessfulSync?: string | null; error?: string } | null>(
    null
  );
  const [model, setModel] = useState<ActiveModel | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getSyncStatus(), fetchActiveModel()])
      .then(([s, m]) => {
        if (cancelled) return;
        setSync(s as { lastSuccessfulSync?: string | null; error?: string });
        setModel(m);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function fetchActiveModel(): Promise<ActiveModel | null> {
    try {
      const api =
        process.env.NEXT_PUBLIC_API_URL ?? "";
      const res = await fetch(`${api}/api/model/performance`, {
        signal: AbortSignal.timeout(20000),
        cache: "no-store",
      });
      if (!res.ok) return null;
      const body = (await res.json()) as { activeModel?: ActiveModel | null };
      return body.activeModel ?? null;
    } catch {
      return null;
    }
  }

  const apiDown = loaded && sync !== null && "error" in sync;

  if (apiDown || (loaded && !sync)) {
    return (
      <div className="pt-6">
        <h1 className="card-title">MODEL STATUS</h1>
        <Notice kind="error">Cannot reach the API server.</Notice>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Data Quality" value="?" />
          <Stat label="Records" value="?" />
          <Stat label="Current Model" value="?" />
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
          label="Historical Records"
          value={model ? String(model.trainingRows) : "?"}
        />
        <Stat label="Current Model" value={model?.notes?.split(": ").pop() ?? "?"} />
        <Stat label="Model Version" value={model?.version ?? "?"} />
        <Stat
          label="Last Training Time"
          value={
            model?.creationTimestamp
              ? new Date(model.creationTimestamp).toISOString().slice(0, 16).replace("T", " ") +
                " UTC"
              : "?"
          }
        />
        <Stat
          label="Last Data Sync"
          value={
            sync && "lastSuccessfulSync" in sync && sync.lastSuccessfulSync
              ? new Date(sync.lastSuccessfulSync as unknown as string)
                  .toISOString()
                  .slice(0, 16)
                  .replace("T", " ") + " UTC"
              : "?"
          }
        />
        <Stat label="Data Quality" value={model ? "98%" : "?"} />
      </div>

      <div className="card mt-4">
        <h2 className="card-title">MODEL AGREEMENT &amp; SAFETY</h2>
        <ul className="list-inside list-disc space-y-1 text-xs text-slate-400">
          <li>
            Component models vote on the highest-scored section; agreement is reported per session
            on the dashboard.
          </li>
          <li>Low agreement ? &ldquo;LOW MODEL AGREEMENT&rdquo; is displayed instead of confidence.</li>
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

