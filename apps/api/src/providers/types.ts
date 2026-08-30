import type { SessionType } from "@thai2d/shared";

/**
 * A single raw record returned by any data provider, before normalization.
 * Providers are responsible for mapping their native format into this shape
 * and for NEVER inventing values they did not receive.
 */
export interface RawResultRecord {
  /** Myanmar-local session date "YYYY-MM-DD". */
  date: string;
  session: SessionType;
  setValue: number | null;
  marketValue: number | null;
  twod: string | number;
  /** UTC ISO timestamp of the source event when the provider supplies one. */
  sourceTimestampUtc?: string | null;
}

export interface FetchOptions {
  days?: number;
  fromDate?: string;
  toDate?: string;
}

/** Modular provider contract — swap sources without touching the engine. */
export interface DataProvider {
  readonly name: string;
  /** Mock providers must declare themselves; production ingestion rejects them. */
  readonly isMock: boolean;
  fetchLatest(): Promise<RawResultRecord[]>;
  fetchHistory(opts?: FetchOptions): Promise<RawResultRecord[]>;
}

export class ProviderError extends Error {
  constructor(
    public readonly provider: string,
    message: string,
    public readonly cause?: unknown
  ) {
    super(`[${provider}] ${message}`);
    this.name = "ProviderError";
  }
}
