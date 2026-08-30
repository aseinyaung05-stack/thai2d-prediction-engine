import { config } from "../config";
import { prisma } from "../db";

export interface QualityGate {
  passed: boolean;
  score: number;
  reasons: string[];
}

/**
 * DATA QUALITY SCORE (0-100), built from measurable components:
 *   completeness (expected 2 sessions per trading day over trailing window)
 *   duplicate rate, invalid records, missing sessions, future timestamps,
 *   source freshness.
 * A gate() check must pass before the engine may generate predictions.
 */
export async function computeDataQuality(): Promise<{
  score: number;
  totalRecords: number;
  duplicateCount: number;
  invalidCount: number;
  missingSessions: number;
  futureTimestamps: number;
  staleHours: number | null;
  warnings: string[];
}> {
  const warnings: string[] = [];
  const totalRecords = await prisma.result.count();
  if (totalRecords === 0) {
    return {
      score: 0,
      totalRecords: 0,
      duplicateCount: 0,
      invalidCount: 0,
      missingSessions: 0,
      futureTimestamps: 0,
      staleHours: null,
      warnings: ["No data ingested yet."],
    };
  }

  // Duplicates: same Myanmar-local date AND session with the identical result
  // is a true duplicate; the same number across both sessions is legitimate.
  const dupRows = await prisma.result.groupBy({
    by: ["date", "session", "twod"],
    _count: { _all: true },
    having: { twod: { _count: { gte: 2 } } },
    orderBy: [{ date: "desc" }],
    take: 200,
  });
  const duplicateCount = dupRows.length;

  // Future timestamps (clock/data corruption signal).
  const futureTimestamps = await prisma.result.count({
    where: { sourceTimestamp: { gt: new Date(Date.now() + 5 * 60_000) } },
  });

  // Rejected records from sync logs.
  const rejectedAgg = await prisma.dataSyncLog.aggregate({
    _sum: { recordsRejected: true },
  });
  const invalidCount = rejectedAgg._sum.recordsRejected ?? 0;

  // Missing sessions: trading days in trailing 60d with only one session.
  const since = new Date(Date.now() - 60 * 24 * 3600_000);
  const grouped = await prisma.result.groupBy({
    by: ["date"],
    where: { date: { gte: since }, sourceTimestamp: { lte: new Date() } },
    _count: { session: true },
    orderBy: [{ date: "desc" }],
  });
  let missingSessions = 0;
  for (const g of grouped) {
    if ((g._count.session ?? 0) < 2) missingSessions++;
    const dow = new Date(g.date).getUTCDay();
    if (dow === 0 || dow === 6) missingSessions--; // weekends are not draws
  }
  missingSessions = Math.max(0, missingSessions);

  // Freshness of latest source event.
  const latest = await prisma.result.findFirst({
    orderBy: { sourceTimestamp: "desc" },
    select: { sourceTimestamp: true },
  });
  const staleHours = latest
    ? Math.max(0, (Date.now() - latest.sourceTimestamp.getTime()) / 3600_000)
    : null;

  // Weighted scoring.
  const w = {
    duplicates: Math.min(1, duplicateCount / Math.max(20, totalRecords * 0.02)),
    invalid: Math.min(1, invalidCount / Math.max(50, totalRecords * 0.05)),
    missing: Math.min(1, missingSessions / 40),
    future: Math.min(1, futureTimestamps / 5),
    stale: staleHours === null ? 1 : Math.min(1, staleHours / 72),
  };
  const score = Math.round(
    100 *
      (0.3 * (1 - w.duplicates) +
        0.15 * (1 - w.invalid) +
        0.25 * (1 - w.missing) +
        0.1 * (1 - w.future) +
        0.2 * (1 - w.stale))
  );

  if (score < 90) warnings.push("Data quality below 90% — treat analysis with caution.");
  if (w.stale === 1) warnings.push("Source data appears stale (>72h old).");
  if (missingSessions > 4) warnings.push(`${missingSessions} trading days have missing sessions.`);

  return {
    score,
    totalRecords,
    duplicateCount,
    invalidCount,
    missingSessions,
    futureTimestamps,
    staleHours: staleHours === null ? null : Math.round(staleHours * 10) / 10,
    warnings,
  };
}

/** Hard gate before prediction generation (spec §16 additional constraints). */
export async function qualityGate(): Promise<QualityGate> {
  const q = await computeDataQuality();
  const reasons: string[] = [];
  if (q.totalRecords < 100) reasons.push(`Only ${q.totalRecords} records (<100 minimum).`);
  if (q.futureTimestamps > 0) reasons.push(`${q.futureTimestamps} future timestamps found.`);
  if (config.strictValidation && q.staleHours !== null && q.staleHours > 96)
    reasons.push("Source data older than 96 hours.");
  return { passed: reasons.length === 0, score: q.score, reasons };
}
