import "server-only";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:4000";

async function getJson<T>(path: string, timeoutMs = 8000): Promise<T | { error: string }> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
    if (!res.ok) return { error: `HTTP ${res.status}` };
    return (await res.json()) as T;
  } catch {
    return { error: "unreachable" };
  }
}

/* ----------------------------- dashboard types ---------------------------- */

export interface SectionScore {
  section: string;
  label?: string;
  range?: string;
  score: number;
  probability: number;
  rank: number;
  candidate_count?: number;
  historical_hit_rate?: number | null;
  explanation?: string[];
}

export interface TopNumber {
  number: string;
  rank: number;
  score: number;
  calibrated_probability?: number;
  raw_score?: number;
  section: string;
  confidence_tier?: string;
  supporting_factors?: string[];
  contradicting_factors?: string[];
}

export interface SessionPrediction {
  session?: string;
  date?: string;
  view?: {
    headline?: {
      highest_model_scored_section?: string;
      top_candidates?: string[];
      wording_note?: string;
    };
    section_ranking?: string;
    tier_notice?: string;
    edge_detected?: boolean;
    edge_notice?: string | null;
    model_agreement?: string;
    data_quality_score?: number;
    disclaimer?: string;
  };
  top10?: TopNumber[];
  section_scores?: SectionScore[];
  model_confidence?: number;
  model_agreement_ratio?: number;
  prediction_id?: string | null;
  stale?: boolean;
  error?: string;
}

export interface TodayPayload {
  date?: string;
  sessions?: Record<string, SessionPrediction>;
  notice?: string;
  error?: string;
}

export const getToday = () => getJson<TodayPayload>("/api/prediction/today", 20000);

/* -------------------------------- history -------------------------------- */

export interface ResultRow {
  date: string;
  session: string;
  twod: string;
  setValue: number | null;
  marketValue: number | null;
  source: string;
  sourceTimestamp: string;
}

export const getHistory = (limit = 40) =>
  getJson<{ results: ResultRow[] }>(`/api/results/latest?n=${limit}`);

/* -------------------------------- backtest ------------------------------- */

export interface BacktestRow {
  id: string;
  modelName: string;
  modelVersion: string;
  testEnd: string;
  nPredictions: number;
  metrics: {
    top1_hit_rate?: number;
    top5_hit_rate?: number;
    top10_hit_rate?: number;
    section_accuracy?: number;
    log_loss?: number;
    brier_score?: number;
    uniform_log_loss_reference?: number;
  };
  baselineComparison?: Record<string, { val_log_loss?: number }>;
  isProduction: boolean;
}

export const getBacktests = () => getJson<{ backtests: BacktestRow[] }>("/api/backtest");

/* --------------------------------- status -------------------------------- */

export interface SyncStatus {
  lastSuccessfulSync: string | null;
  lastAttempt?: { at: string; status: string; provider: string; inserted: number } | null;
}

export const getSyncStatus = () => getJson<SyncStatus>("/api/sync/status");
