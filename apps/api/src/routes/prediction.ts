import { Router } from "express";
import { Prisma } from "@prisma/client";
import type { SessionType } from "@thai2d/shared";
import { config } from "../config";
import { prisma } from "../db";
import { attachPendingOutcomes } from "../services/outcomes";

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
        highest_model_scored_section: best ? `SECTION ${best.section}` : "?",
        top_candidates: topCandidates.slice(0, 5).map((t) => String(t.number)),
        wording_note: "Highest model-scored section ? NOT a guaranteed section.",
      },
      section_ranking: [...sections]
        .sort((a, b) => Number(a.rank) - Number(b.rank))
        .map((s) => `${s.section} ${(Number(s.probability) * 100).toFixed(1)}%`)
        .join(" ? "),
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
 * snapshot exists yet, with a bounded timeout ? a cold engine pipeline can
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

    // 2. No snapshot yet ? ask the engine, but bounded so clients never hang.
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
    out.notice = "Live source unavailable ? using cached data.";
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
        .json({ error: "No valid data available ? no cached prediction exists." });
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

/**
 * GET /api/prediction/monthly-performance?month=YYYY-MM
 *
 * Month-to-date prediction scorecard: for every graded prediction in the
 * month (a stored snapshot whose draw has been realized), compare the
 * predicted highest-scored section with the actual result's section.
 *
 * SECTION HIT % = section hits / graded predictions.
 * Benchmark: 25% is random chance when picking 1 of 4 sections.
 */
predictionRouter.get("/monthly-performance", async (req, res) => {
  const monthParam = typeof req.query.month === "string" ? req.query.month : null;
  const nowYangon = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Yangon",
    year: "numeric",
    month: "2-digit",
  }).format(new Date());
  const month = monthParam && /^\d{4}-\d{2}$/.test(monthParam) ? monthParam : nowYangon;

  // Make sure realized draws are attached to stored snapshots first.
  try {
    await attachPendingOutcomes();
  } catch {
    /* outcomes attachment is best-effort; stale grading is acceptable */
  }

  const startDate = new Date(`${month}-01T00:00:00Z`);
  const [yy, mm] = month.split("-").map(Number);
  const endDate = new Date(Date.UTC(yy, mm, 1)); // first day of next month

  const runs = await prisma.predictionRun.findMany({
    where: {
      sessionDate: { gte: startDate, lt: endDate },
      actualResult: { not: null },
    },
    orderBy: [{ sessionDate: "asc" }, { session: "asc" }],
  });

  // Keep only the LATEST graded run per (date, session) so repeat
  // generations never double-count the same draw.
  const latestByDraw = new Map<string, (typeof runs)[number]>();
  for (const run of runs) {
    const key = `${run.sessionDate.toISOString().slice(0, 10)}|${run.session}`;
    const prev = latestByDraw.get(key);
    if (!prev || prev.predictionTimestampUtc < run.predictionTimestampUtc) {
      latestByDraw.set(key, run);
    }
  }

  let graded = 0;
  let sectionHits = 0;
  let top10Hits = 0;
  let top1Hits = 0;
  const bySession: Record<string, { graded: number; section_hits: number; top10_hits: number }> = {
    MORNING: { graded: 0, section_hits: 0, top10_hits: 0 },
    AFTERNOON: { graded: 0, section_hits: 0, top10_hits: 0 },
  };
  const detail: Array<Record<string, unknown>> = [];

  for (const run of latestByDraw.values()) {
    const sections = (run.sectionScores ?? []) as Array<Record<string, unknown>>;
    const best = [...sections].sort(
      (a, b) => Number(a.rank ?? 99) - Number(b.rank ?? 99)
    )[0];
    const predictedSection = best ? String(best.section) : null;
    if (!predictedSection || !run.actualSection) continue;

    graded++;
    const hit = predictedSection === run.actualSection;
    if (hit) sectionHits++;
    if (run.actualTop10Hit) top10Hits++;
    if (run.predictionOutcome === "TOP_1") top1Hits++;

    const sess = run.session as string;
    bySession[sess] ??= { graded: 0, section_hits: 0, top10_hits: 0 };
    bySession[sess].graded++;
    if (hit) bySession[sess].section_hits++;
    if (run.actualTop10Hit) bySession[sess].top10_hits++;

    const runTop10 = (run.top10 ?? []) as Array<Record<string, unknown>>;
    detail.push({
      date: run.sessionDate,
      session: run.session,
      model_version: run.modelVersion,
      predicted_section: predictedSection,
      predicted_top_number: runTop10.length
        ? String(runTop10[0].number)
        : null,
      actual_result: run.actualResult,
      actual_section: run.actualSection,
      section_hit: hit,
      actual_rank: run.actualRank,
      top10_hit: run.actualTop10Hit,
      outcome: run.predictionOutcome,
    });
  }

  const pct = (hits: number) => (graded ? Number(((hits / graded) * 100).toFixed(1)) : null);

  res.json({
    month,
    graded,
    section_hits: sectionHits,
    section_hit_pct: pct(sectionHits),
    top10_hits: top10Hits,
    top10_pct: pct(top10Hits),
    top1_hits: top1Hits,
    top1_pct: pct(top1Hits),
    chance_benchmark: { section_pct: 25, top10_pct: 10, top1_pct: 1 },
    by_session: bySession,
    detail,
    disclaimer:
      "Section hit = the predicted highest-scored section matched the actual result's section. 25% / 10% / 1% are the random-chance benchmarks for 4 sections / top-10 of 100 / top-1 of 100. Past performance does not guarantee future results.",
  });
});


