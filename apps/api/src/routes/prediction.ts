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

type StoredRun = Prisma.PredictionRunGetPayload<{
  include: { scores: { orderBy: { rank: "asc" }; take: 10 } };
}>;

/** Rebuild the API view object from a stored immutable snapshot row. */
function storedToSessionView(row: StoredRun): Json {
  const sections = (row.sectionScores ?? []) as Array<Json>;
  const top10 = (row.top10 ?? []) as Array<Json>;
  const best = [...sections].sort((a, b) => Number(a.rank) - Number(b.rank))[0];
  const ratio = row.modelAgreementRatio;
  const agreement =
    ratio >= 0.75
      ? "HIGH MODEL AGREEMENT"
      : ratio >= 0.5
        ? "MODERATE MODEL AGREEMENT"
        : "LOW MODEL AGREEMENT";
  const fallbackTop = (row.scores ?? []).map((sc) => ({
    number: sc.number,
    rank: sc.rank,
    score: sc.calibratedProbability,
    section: sc.section,
    calibrated_probability: sc.calibratedProbability,
  }));
  const topCandidates = top10.length
    ? top10
    : (fallbackTop as unknown as Array<Json>);
  return {
    ...(row as unknown as Json),
    top10: topCandidates,
    section_scores: sections,
    view: {
      headline: {
        highest_model_scored_section: best ? `SECTION ${best.section}` : "—",
        top_candidates: topCandidates.slice(0, 5).map((t) => String(t.number)),
        wording_note: "Highest model-scored section — NOT a guaranteed section.",
      },
      section_ranking: [...sections]
        .sort((a, b) => Number(a.rank) - Number(b.rank))
        .map((s) => `${s.section} ${(Number(s.probability) * 100).toFixed(1)}%`)
        .join(" — "),
      edge_detected: row.edgeDetected,
      edge_notice: row.edgeNotice,
      model_agreement: agreement,
      tier_notice: "",
      disclaimer:
        "This application provides statistical analysis based on historical market/2D data. Model scores are estimates, not guarantees. Historical performance does not guarantee future results.",
    },
    model_agreement_ratio: ratio,
    model_confidence: row.modelConfidence,
    data_quality_score: row.dataQualityScore,
  };
}

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
 * STORED-FIRST design: the immutable snapshot for (today, session) is served
 * instantly from PostgreSQL. The live engine is only consulted when no
 * snapshot exists yet, with a bounded timeout — a cold engine pipeline can
 * take minutes, which would otherwise outrun every client.
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
  const d = new Date(`${yangonToday}T00:00:00Z`);

  for (const s of SESSIONS) {
    // 1. Instant path: today's stored immutable snapshot.
    const storedToday = await prisma.predictionRun.findFirst({
      where: { sessionDate: d, session: sessionFilter(s) },
      orderBy: { predictionTimestampUtc: "desc" },
      include: { scores: { orderBy: { rank: "asc" }, take: 10 } },
    });
    if (storedToday) {
      sessionsOut[s] = { ...storedToSessionView(storedToday), stale: false };
      anyLive = true;
      // Fire-and-forget background refresh so the next request is fresh.
      void proxyPrediction(`/predict/${s}?date=${yangonToday}`).catch(() => {});
      continue;
    }

    // 2. No snapshot yet — ask the engine, but bounded so clients never hang.
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 45000);
      const r = await fetch(`${config.predictionServiceUrl}/predict/${s}?date=${yangonToday}`, {
        headers: {
          Authorization: `Bearer ${config.predictionApiToken}`,
          Accept: "application/json",
        },
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (r.ok) {
        const body = (await r.json()) as Json;
        sessionsOut[s] = { ...body, stale: false };
        anyLive = true;
        continue;
      }
    } catch {
      /* fall through */
    }

    // 3. Latest stored run for this session (any date), clearly flagged.
    const latest = await prisma.predictionRun.findFirst({
      where: { session: sessionFilter(s) },
      orderBy: { predictionTimestampUtc: "desc" },
      include: { scores: { orderBy: { rank: "asc" }, take: 10 } },
    });
    sessionsOut[s] = latest
      ? { ...storedToSessionView(latest), stale: true }
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
