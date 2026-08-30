import { Router } from "express";
import { Prisma } from "@prisma/client";
import type { SessionType } from "@thai2d/shared";
import { config } from "../config";
import { prisma } from "../db";

export const predictionRouter = Router();

const SESSIONS: SessionType[] = ["MORNING", "AFTERNOON"];

function isSession(v: string): v is SessionType {
  return SESSIONS.includes(v as SessionType);
}

function sessionFilter(s: SessionType): Prisma.PredictionRunWhereInput["session"] {
  return s as unknown as Prisma.PredictionRunWhereInput["session"];
}

type Json = Record<string, unknown>;

/** Proxy a request to the Python prediction service with the internal token. */
async function proxyPrediction(path: string, method: "GET" | "POST" = "GET"): Promise<Response> {
  return fetch(`${config.predictionServiceUrl}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${config.predictionApiToken}`,
      Accept: "application/json",
    },
  });
}

/**
 * GET /api/prediction/today
 * Both sessions. Falls back to the latest stored immutable run when the
 * live engine is unreachable — clearly flagged as cached.
 */
predictionRouter.get("/today", async (_req, res) => {
  const today = new Date();
  const yangonToday = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Yangon",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(today);

  const sessionsOut: Record<string, Json> = {};
  let anyLive = false;

  for (const s of SESSIONS) {
    try {
      const r = await proxyPrediction(`/predict/${s}?date=${yangonToday}`);
      if (r.ok) {
        const body = (await r.json()) as Json;
        sessionsOut[s] = { ...body, stale: false };
        anyLive = true;
        continue;
      }
    } catch {
      /* fall through to stored snapshot */
    }
    const d = new Date(`${yangonToday}T00:00:00Z`);
    const stored = await prisma.predictionRun.findFirst({
      where: { sessionDate: d, session: sessionFilter(s) },
      orderBy: { predictionTimestampUtc: "desc" },
      include: { scores: { orderBy: { rank: "asc" }, take: 10 } },
    });
    sessionsOut[s] = stored
      ? ({ ...(stored as unknown as Json), stale: true } as Json)
      : { error: "No prediction available for this session yet.", stale: true };
  }

  const out: Json = { date: yangonToday, sessions: sessionsOut };
  if (!anyLive) {
    out.notice = "Live source unavailable — using cached data.";
  }
  res.json(out);
});

/** GET /api/prediction/:session */
predictionRouter.get("/:session", async (req, res) => {
  const s = req.params.session.toUpperCase();
  if (!isSession(s)) return res.status(400).json({ error: "session must be MORNING or AFTERNOON" });
  try {
    const r = await proxyPrediction(`/predict/${s}`);
    if (r.ok) {
      const body = (await r.json()) as Json;
      return res.json({ ...body, stale: false });
    }
    throw new Error(`engine HTTP ${r.status}`);
  } catch {
    // Fallback: latest stored snapshot for this session.
    const stored = await prisma.predictionRun.findFirst({
      where: { session: sessionFilter(s) },
      orderBy: { predictionTimestampUtc: "desc" },
      include: { scores: { orderBy: { rank: "asc" }, take: 25 } },
    });
    if (!stored)
      return res
        .status(503)
        .json({ error: "No valid data available — no cached prediction exists." });
    return res.json({ ...(stored as unknown as Json), stale: true });
  }
});

/** GET /api/prediction/:session/top */
predictionRouter.get("/:session/top", async (req, res) => {
  const s = req.params.session.toUpperCase();
  const n = Math.min(50, Math.max(1, Number(req.query.n) || 10));
  if (!isSession(s)) return res.status(400).json({ error: "session must be MORNING or AFTERNOON" });
  try {
    const r = await proxyPrediction(`/predict/${s}/top?n=${n}`);
    if (r.ok) return res.json(await r.json());
    throw new Error(`engine HTTP ${r.status}`);
  } catch {
    const stored = await prisma.predictionRun.findFirst({
      where: { session: sessionFilter(s) },
      orderBy: { predictionTimestampUtc: "desc" },
      include: { scores: { orderBy: { rank: "asc" }, take: n } },
    });
    if (!stored) return res.status(503).json({ error: "No valid data available." });
    const top = stored.scores.map((sc) => ({
      number: sc.number,
      rank: sc.rank,
      raw_score: sc.rawScore,
      calibrated_probability: sc.calibratedProbability,
      section: sc.section,
    }));
    return res.json({ session: s, top, stale: true });
  }
});

/** GET /api/prediction/:session/sections */
predictionRouter.get("/:session/sections", async (req, res) => {
  const s = req.params.session.toUpperCase();
  if (!isSession(s)) return res.status(400).json({ error: "session must be MORNING or AFTERNOON" });
  try {
    const r = await proxyPrediction(`/predict/${s}/sections`);
    if (r.ok) return res.json(await r.json());
    throw new Error(`engine HTTP ${r.status}`);
  } catch {
    const stored = await prisma.predictionRun.findFirst({
      where: { session: sessionFilter(s) },
      orderBy: { predictionTimestampUtc: "desc" },
    });
    if (!stored?.sectionScores)
      return res.status(503).json({ error: "No valid data available." });
    return res.json({
      session: s,
      sections: stored.sectionScores,
      stale: true,
    });
  }
});
