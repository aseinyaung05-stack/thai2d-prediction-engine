import { config } from "../config";
import type { DataProvider, FetchOptions, RawResultRecord } from "./types";

/**
 * DEVELOPMENT-ONLY provider. Every record it emits is clearly marked MOCK and
 * production ingestion (ALLOW_MOCK_DATA=false) rejects mock records outright.
 * The prediction engine never sees fabricated data unless explicitly running
 * in development mode with this provider selected.
 */
export class MockDataProvider implements DataProvider {
  readonly name = "mock";
  readonly isMock = true;

  constructor(private readonly days: number = 400) {
    if (!config.allowMockData) {
      throw new Error("MockDataProvider is disabled: ALLOW_MOCK_DATA=false");
    }
  }

  async fetchLatest(): Promise<RawResultRecord[]> {
    return this.lastDayRecords(0);
  }

  async fetchHistory(opts: FetchOptions = {}): Promise<RawResultRecord[]> {
    const out: RawResultRecord[] = [];
    const n = Math.min(opts.days ?? this.days, this.days);
    for (let i = n; i >= 1; i--) {
      for (const rec of this.dayRecords(i)) out.push(rec);
    }
    return out;
  }

  private lastDayRecords(daysAgo: number): RawResultRecord[] {
    return this.dayRecords(daysAgo);
  }

  /** Deterministic pseudo-random generator so tests are reproducible. */
  private dayRecords(daysAgo: number): RawResultRecord[] {
    const base = new Date();
    base.setUTCHours(0, 0, 0, 0);
    base.setUTCDate(base.getUTCDate() - daysAgo);
    const iso = base.toISOString().slice(0, 10);
    // Skip weekends to mirror Thai trading calendar.
    const dow = base.getUTCDay();
    if (dow === 0 || dow === 6) return [];

    let seed = hashCode(iso) >>> 0;
    const rand = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 2 ** 32;
    };

    const sessions = [
      { session: "MORNING" as const, utcHour: 5, utcMinute: 30 },
      { session: "AFTERNOON" as const, utcHour: 10, utcMinute: 0 },
    ];
    return sessions.map((s) => {
      const value = Math.floor(rand() * 100);
      const ts = new Date(base);
      ts.setUTCHours(s.utcHour, s.utcMinute - 30, 0, 0); // event slightly before cutoff
      return {
        date: iso,
        session: s.session,
        setValue: Math.floor(rand() * 2000),
        marketValue: Math.floor(rand() * 2000),
        twod: value.toString().padStart(2, "0"),
        sourceTimestampUtc: ts.toISOString(),
      };
    });
  }
}

function hashCode(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
