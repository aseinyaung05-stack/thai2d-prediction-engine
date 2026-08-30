import { classifySection, normalizeTwod } from "@thai2d/shared";
import { prisma } from "../db";

/**
 * Attach realized results to immutable prediction snapshots.
 * The original prediction columns are never modified — only the
 * outcome_* fields are appended once the actual result is known.
 */
export async function attachPendingOutcomes(): Promise<number> {
  const pending = await prisma.predictionRun.findMany({
    where: {
      sourceDataCutoffUtc: { lte: new Date() },
      actualResult: null,
    },
    take: 500,
    orderBy: { sourceDataCutoffUtc: "asc" },
  });

  let attached = 0;
  for (const run of pending) {
    const result = await prisma.result.findFirst({
      where: {
        date: run.sessionDate,
        session: run.session,
      },
    });
    if (!result) continue;

    const scores = await prisma.predictionScore.findMany({
      where: { runId: run.id },
      orderBy: { rank: "asc" },
    });
    const rank = scores.findIndex((s) => s.number === result.twod) + 1;

    await prisma.predictionRun.update({
      where: { id: run.id },
      data: {
        actualResult: result.twod,
        actualSection: classifySection(parseInt(result.twod, 10)),
        actualRank: rank > 0 ? rank : null,
        actualTop10Hit: rank >= 1 && rank <= 10,
        predictionOutcome:
          rank === 1 ? "TOP_1" : rank <= 3 ? "TOP_3" : rank <= 10 ? "TOP_10" : "MISS",
        outcomeAttachedAt: new Date(),
      },
    });
    attached++;
  }
  return attached;
}

/** Normalize a CSV row value into a twod string or null. */
export function csvTwod(v: string): string | null {
  return normalizeTwod(v);
}
