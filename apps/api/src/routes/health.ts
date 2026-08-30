import { Router } from "express";
import { config } from "../config";
import { prisma } from "../db";
import { computeDataQuality } from "../services/quality";
import { nextSession, formatYangon } from "@thai2d/shared";

export const healthRouter = Router();

healthRouter.get("/health", async (_req, res) => {
  let dbOk = true;
  try {
    await prisma.$queryRaw`SELECT 1`;
  } catch {
    dbOk = false;
  }
  let engineOk = false;
  try {
    const r = await fetch(`${config.predictionServiceUrl}/health`, {
      headers: { Authorization: `Bearer ${config.predictionApiToken}` },
      signal: AbortSignal.timeout(3000),
    });
    engineOk = r.ok;
  } catch {
    engineOk = false;
  }
  const nxt = nextSession();
  res.json({
    status: dbOk ? "ok" : "degraded",
    services: { database: dbOk, predictionEngine: engineOk },
    nowUtc: new Date().toISOString(),
    nowYangon: formatYangon(new Date()),
    nextSession: {
      session: nxt.session,
      sessionDate: nxt.sessionDate,
      cutoffYangon: formatYangon(nxt.cutoffUtc),
      msRemaining: nxt.cutoffUtc.getTime() - Date.now(),
    },
  });
});
