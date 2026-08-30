import { Router } from "express";
import type { SessionType } from "@thai2d/shared";
import { prisma } from "../db";

export const resultsRouter = Router();

function parseSession(v: string): SessionType | null {
  return v === "MORNING" || v === "AFTERNOON" ? v : null;
}

const selection = {
  date: true,
  session: true,
  twod: true,
  digitTens: true,
  digitOnes: true,
  setValue: true,
  marketValue: true,
  source: true,
  sourceTimestamp: true,
};

/** GET /api/results/latest */
resultsRouter.get("/latest", async (req, res, next) => {
  try {
    const take = Math.min(20, Math.max(1, Number(req.query.n) || 1));
    const rows = await prisma.result.findMany({
      orderBy: [{ date: "desc" }, { session: "desc" }],
      take,
      select: selection,
    });
    res.json({ results: rows });
  } catch (err) {
    next(err);
  }
});

/** GET /api/results/history?limit=500&session=MORNING&from=YYYY-MM-DD */
resultsRouter.get("/history", async (req, res, next) => {
  try {
    const limit = Math.min(5000, Math.max(1, Number(req.query.limit) || 500));
    const sessionParam = typeof req.query.session === "string" ? req.query.session : "";
    const where: Record<string, unknown> = {};
    if (sessionParam) {
      const s = parseSession(sessionParam);
      if (!s) return res.status(400).json({ error: "session must be MORNING or AFTERNOON" });
      where.session = s;
    }
    if (typeof req.query.from === "string") where.date = { gte: new Date(`${req.query.from}T00:00:00Z`) };
    if (typeof req.query.to === "string")
      where.date = { ...(where.date as object), lte: new Date(`${req.query.to}T00:00:00Z`) };

    const rows = await prisma.result.findMany({
      where,
      orderBy: [{ date: "asc" }, { session: "asc" }],
      take: limit,
      select: selection,
    });
    res.json({ count: rows.length, results: rows });
  } catch (err) {
    next(err);
  }
});

/** GET /api/results/date/:date — both sessions of one Myanmar-local day. */
resultsRouter.get("/date/:date", async (req, res, next) => {
  try {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(req.params.date))
      return res.status(400).json({ error: "date must be YYYY-MM-DD" });
    const d = new Date(`${req.params.date}T00:00:00.000Z`);
    if (Number.isNaN(d.getTime())) return res.status(400).json({ error: "invalid date" });
    const rows = await prisma.result.findMany({
      where: { date: d },
      orderBy: { session: "asc" },
      select: selection,
    });
    res.json({ date: req.params.date, results: rows });
  } catch (err) {
    next(err);
  }
});
