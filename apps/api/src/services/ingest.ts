import { createHash } from "node:crypto";
import {
  normalizeTwod,
  sectionOfTwod,
  sessionCutoffUtc,
  type SessionType,
} from "@thai2d/shared";
import { prisma } from "../db";
import { config } from "../config";
import { getProvider } from "../providers";
import { validateRawRecord, type RawResultRecordLike } from "./validation";

export interface IngestStats {
  fetched: number;
  inserted: number;
  skipped: number;
  rejected: number;
}

/** Canonical hash for duplicate detection across providers/re-imports. */
export function rawRecordHash(rec: RawResultRecordLike): string {
  const canonical = JSON.stringify([
    rec.date,
    rec.session,
    normalizeTwod(rec.twod),
    rec.sourceTimestampUtc ?? null,
  ]);
  return createHash("sha256").update(canonical).digest("hex");
}

/**
 * Validate + dedupe + persist a batch of records.
 * - Rejects invalid records (bad dates/sessions/2D values/future timestamps).
 * - Dedupes inside the batch and against DB (rawRecordHash unique + date/session unique).
 * - Mock records are refused unless ALLOW_MOCK_DATA=true.
 */
export async function ingestRecords(
  records: RawResultRecordLike[],
  opts: { source: string; sourceUrl?: string | null }
): Promise<IngestStats> {
  const stats: IngestStats = { fetched: records.length, inserted: 0, skipped: 0, rejected: 0 };

  // Pass 1: validate & normalize.
  const valid: Array<{
    date: Date;
    session: SessionType;
    twod: string;
    digitTens: number;
    digitOnes: number;
    setValue: number | null;
    marketValue: number | null;
    sourceTimestamp: Date;
    rawRecordHash: string;
  }> = [];
  for (const rec of records) {
    if (rec.source === "mock" && !config.allowMockData) {
      stats.rejected++;
      continue;
    }
    const check = validateRawRecord(rec);
    if (!check.ok) {
      stats.rejected++;
      continue;
    }
    const twod = normalizeTwod(rec.twod)!;
    const tens = parseInt(twod[0], 10);
    const ones = parseInt(twod[1], 10);
    const ts = rec.sourceTimestampUtc ? new Date(rec.sourceTimestampUtc) : cutoffFallback(rec.date, rec.session);
    valid.push({
      date: new Date(`${rec.date}T00:00:00.000Z`),
      session: rec.session as SessionType,
      twod,
      digitTens: tens,
      digitOnes: ones,
      setValue: rec.setValue ?? null,
      marketValue: rec.marketValue ?? null,
      sourceTimestamp: ts,
      rawRecordHash: createHash("sha256")
        .update(
          JSON.stringify([
            rec.date,
            rec.session,
            twod,
            rec.sourceTimestampUtc ?? ts.toISOString(),
          ])
        )
        .digest("hex"),
    });
  }

  // Pass 2: intra-batch dedupe (keep first occurrence).
  const seenHash = new Set<string>();
  const seenKey = new Set<string>();
  const batch = valid.filter((r) => {
    const key = `${r.date.toISOString().slice(0, 10)}|${r.session}`;
    if (seenHash.has(r.rawRecordHash) || seenKey.has(key)) {
      stats.skipped++;
      return false;
    }
    seenHash.add(r.rawRecordHash);
    seenKey.add(key);
    return true;
  });

  // Pass 3: persist with DB-level duplicate protection.
  for (const r of batch) {
    try {
      await prisma.result.upsert({
        where: { date_session: { date: r.date, session: r.session } },
        update: {}, // existing raw data is never overwritten
        create: {
          date: r.date,
          session: r.session,
          twod: r.twod,
          digitTens: r.digitTens,
          digitOnes: r.digitOnes,
          setValue: r.setValue,
          marketValue: r.marketValue,
          source: opts.source,
          sourceUrl: opts.sourceUrl ?? null,
          sourceTimestamp: r.sourceTimestamp,
          localSessionDate: r.date,
          rawRecordHash: r.rawRecordHash,
        },
      });
      stats.inserted++;
    } catch {
      stats.skipped++;
    }
  }
  return stats;
}

function cutoffFallback(date: string, session: string): Date {
  const s = (session === "AFTERNOON" ? "AFTERNOON" : "MORNING") as SessionType;
  // Event time is recorded slightly before its Yangon cutoff.
  const cut = sessionCutoffUtc(date, s);
  return new Date(cut.getTime() - 30 * 60_000);
}

/** Run a full sync against a provider, writing an auditable DataSyncLog. */
export async function syncFromProvider(
  trigger: "manual" | "scheduled" | "startup",
  providerName?: string,
  days?: number
) {
  const provider = getProvider(providerName);
  const log = await prisma.dataSyncLog.create({
    data: {
      startedAt: new Date(),
      status: "RUNNING",
      provider: provider.name,
      trigger,
    },
  });

  try {
    const [historyRecords, latestRecords] = await Promise.all([
      safeFetch(() => provider.fetchHistory({ days: days ?? 400 })),
      safeFetch(() => provider.fetchLatest()),
    ]);

    let historyStats: IngestStats = { fetched: 0, inserted: 0, skipped: 0, rejected: 0 };
    let latestStats: IngestStats = { fetched: 0, inserted: 0, skipped: 0, rejected: 0 };
    let partialError: string | null = null;

    if (historyRecords !== null) {
      historyStats = await ingestRecords(historyRecords, {
        source: provider.isMock ? "MOCK" : provider.name,
        sourceUrl: config.thai2dBaseUrl,
      });
    } else {
      partialError = "history fetch failed";
    }

    if (latestRecords !== null && latestRecords.length > 0) {
      latestStats = await ingestRecords(latestRecords, {
        source: provider.isMock ? "MOCK" : `${provider.name}/live`,
        sourceUrl: config.thai2dBaseUrl,
      });
    }

    const merged: IngestStats = {
      fetched: historyStats.fetched + latestStats.fetched,
      inserted: historyStats.inserted + latestStats.inserted,
      skipped: historyStats.skipped + latestStats.skipped,
      rejected: historyStats.rejected + latestStats.rejected,
    };

    const failed = historyRecords === null && latestRecords === null;
    await prisma.dataSyncLog.update({
      where: { id: log.id },
      data: {
        finishedAt: new Date(),
        status: failed ? "FAILED" : partialError ? "PARTIAL" : "SUCCESS",
        recordsFetched: merged.fetched,
        recordsInserted: merged.inserted,
        recordsSkipped: merged.skipped,
        recordsRejected: merged.rejected,
        errorMessage: partialError,
      },
    });

    // After new results land, attach outcomes to past predictions.
    const { attachPendingOutcomes } = await import("./outcomes");
    await attachPendingOutcomes();

    return { logId: log.id, ...merged, status: failed ? "FAILED" : partialError ? "PARTIAL" : "SUCCESS" };
  } catch (err) {
    await prisma.dataSyncLog.update({
      where: { id: log.id },
      data: {
        finishedAt: new Date(),
        status: "FAILED",
        errorMessage: (err as Error).message.slice(0, 500),
      },
    });
    throw err;
  }
}

async function safeFetch<T>(fn: () => Promise<T[]>): Promise<T[] | null> {
  try {
    return await fn();
  } catch (err) {
    console.error("[sync] fetch failed:", (err as Error).message);
    return null;
  }
}
