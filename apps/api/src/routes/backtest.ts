import { Router } from "express";
import { config } from "../config";
import { prisma } from "../db";

export const backtestRouter = Router();

/** GET /api/backtest — recent backtest evaluations (leaderboard-ready). */
backtestRouter.get("/", async (_req, res, next) => {
  try {
    const rows = await prisma.backtest.findMany({
      orderBy: { createdAt: "desc" },
      take: 50,
    });
    res.json({ count: rows.length, backtests: rows });
  } catch (err) {
    next(err);
  }
});

/** POST /api/backtest/run — trigger walk-forward evaluation in the engine. */
backtestRouter.post("/run", async (_req, res) => {
  try {
    const r = await fetch(`${config.predictionServiceUrl}/backtest/run`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.predictionApiToken}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) return res.status(r.status).json(body);
    return res.json(body);
  } catch (err) {
    return res
      .status(503)
      .json({ error: "Prediction service unavailable.", detail: (err as Error).message });
  }
});

/** GET /api/model/performance — production model + drift status. */
export async function modelPerformanceHandler(_req: import("express").Request, res: import("express").Response, next: import("express").NextFunction) {
  try {
    const active = await prisma.modelVersion.findFirst({
      where: { isActive: true },
      orderBy: { creationTimestamp: "desc" },
    });
    let drift: unknown = null;
    try {
      const r = await fetch(`${config.predictionServiceUrl}/monitor/drift`, {
        headers: { Authorization: `Bearer ${config.predictionApiToken}` },
      });
      if (r.ok) drift = await r.json();
    } catch {
      drift = { error: "prediction service unavailable" };
    }
    res.json({ activeModel: active, drift });
  } catch (err) {
    next(err);
  }
}

backtestRouter.get("/model/performance", modelPerformanceHandler);

