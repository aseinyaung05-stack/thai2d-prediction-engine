/**
 * Canonical domain types for the Thai 2D prediction platform.
 * These types are the contract between API, database and frontend.
 */

/** User-facing prediction sessions, defined in Asia/Yangon local time. */
export type SessionType = "MORNING" | "AFTERNOON";

export const SESSIONS: SessionType[] = ["MORNING", "AFTERNOON"];

export const SESSION_LABEL_EN: Record<SessionType, string> = {
  MORNING: "12:00 PM",
  AFTERNOON: "4:30 PM",
};

/** Myanmar-local wall-clock time of each session. */
export const SESSION_LOCAL_TIME: Record<SessionType, { hour: number; minute: number }> = {
  MORNING: { hour: 12, minute: 0 },
  AFTERNOON: { hour: 16, minute: 30 },
};

/** Four equal sections of the 00-99 number space. */
export type SectionId = "A" | "B" | "C" | "D";

export const SECTIONS: SectionId[] = ["A", "B", "C", "D"];

export const SECTION_RANGE: Record<SectionId, { min: number; max: number }> = {
  A: { min: 0, max: 24 },
  B: { min: 25, max: 49 },
  C: { min: 50, max: 74 },
  D: { min: 75, max: 99 },
};

export const SECTION_LABEL: Record<SectionId, string> = {
  A: "SECTION A (00–24)",
  B: "SECTION B (25–49)",
  C: "SECTION C (50–74)",
  D: "SECTION D (75–99)",
};

/** IANA timezone names — never hard-code UTC offsets in application code. */
export const TIMEZONES = {
  THAILAND: "Asia/Bangkok",
  MYANMAR: "Asia/Yangon",
  UTC: "UTC",
} as const;

export interface NormalizedResult {
  /** Myanmar-local session date, e.g. "2026-08-23". */
  date: string;
  session: SessionType;
  setValue: number | null;
  marketValue: number | null;
  /** Two-character zero-padded result, e.g. "01" (never "1"). */
  twod: string;
  digitTens: number;
  digitOnes: number;
  section: SectionId;
  source: string;
  sourceTimestampUtc: string;
}

export interface DataQualityReport {
  score: number;
  totalRecords: number;
  duplicateCount: number;
  invalidCount: number;
  missingSessions: number;
  futureTimestamps: number;
  staleHours: number | null;
  warnings: string[];
}

export interface SectionScoreView {
  section: SectionId;
  score: number;
  probability: number;
  rank: number;
  candidateCount: number;
  historicalHitRate: number | null;
  modelAgreement: number;
  explanation: string[];
}

export interface CandidateView {
  number: string;
  rank: number;
  score: number;
  calibratedProbability: number;
  section: SectionId;
  confidenceTier: "HIGHER MODEL SUPPORT" | "MODERATE MODEL SUPPORT" | "LOW MODEL SUPPORT";
  supportingFactors: string[];
  contradictingFactors: string[];
}

export interface PredictionRunView {
  predictionId: string;
  sessionDate: string;
  session: SessionType;
  predictionTimestampUtc: string;
  sourceDataCutoffUtc: string;
  modelVersion: string;
  featureVersion: string;
  dataTier: "TIER_1" | "TIER_2" | "TIER_3" | "TIER_4";
  edgeDetected: boolean;
  edgeNotice: string | null;
  trainingDataEndDate: string;
  sections: SectionScoreView[];
  top10: CandidateView[];
  componentAgreement: Record<string, SectionId>;
  modelAgreementRatio: number;
  modelConfidence: number;
  dataQualityScore: number;
}
