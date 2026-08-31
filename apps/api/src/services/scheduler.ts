import cron from "node-cron";
import { config } from "../config";
import { prisma } from "../db";
import { syncFromProvider } from "./ingest";

let started = false;

/**
 * Automatic scheduled sync. Runs every SYNC_INTERVAL_MINUTES.
 * Each run is logged; failures never crash the API process — they are
 * recorded in data_sync_logs and surfaced on the admin dashboard.
 */
export function startScheduler(): void {
  if (started) return;
  started = true;

  const interval = Math.max(1, Math.min(59, config.syncIntervalMinutes));
  const expr = `*/${interval} * * * *`;

  // Startup sync (non-blocking, best-effort).
  void runSync("startup");

  cron.schedule(expr, () => void runSync("scheduled"));
  console.log(`[scheduler] auto-sync every ${interval} min (${expr})`);
}

async function runSync(trigger: "startup" | "scheduled"): Promise<void> {
  try {
    const last = await prisma.dataSyncLog.findFirst({
      where: { status: { in: ["SUCCESS", "PARTIAL"] } },
      orderBy: { startedAt: "desc" },
    });
    // Skip if a successful sync ran within the interval window.
    if (
      last?.finishedAt &&
      Date.now() - last.finishedAt.getTime() < (config.syncIntervalMinutes - 1) * 60_000
    )
      return;
    const res = await syncFromProvider(trigger);
    console.log(`[scheduler] sync ${res.status}: +${res.inserted} inserted`);
    void notifyPredictionService();
    void refreshStoredPredictions();
  } catch (err) {
    console.error(`[scheduler] sync failed:`, (err as Error).message);
  }
}

/** Fire-and-forget: regenerate today's stored prediction snapshots so
 *  /api/prediction/today always has fresh data without blocking clients. */
async function refreshStoredPredictions(): Promise<void> {
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Yangon",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  for (const s of ["MORNING", "AFTERNOON"]) {
    try {
      await fetch(
        `${config.predictionServiceUrl}/predict/${s}?date=${today}`,
        {
          headers: {
            Authorization: `Bearer ${config.predictionApiToken}`,
            Accept: "application/json",
          },
        }
      );
      console.log(`[scheduler] refreshed prediction snapshot: ${s}`);
    } catch (err) {
      console.warn(`[scheduler] snapshot refresh ${s} failed:`, (err as Error).message);
    }
  }
}

/** Ping the Python service that fresh data may exist (retraining hook). */
async function notifyPredictionService(): Promise<void> {
  try {
    await fetch(`${config.predictionServiceUrl}/internal/retrain-hook`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${config.predictionApiToken}`,
      },
      body: JSON.stringify({ reason: "new_data" }),
    });
  } catch {
    // Prediction service may be down; retraining can be triggered manually.
  }
}
