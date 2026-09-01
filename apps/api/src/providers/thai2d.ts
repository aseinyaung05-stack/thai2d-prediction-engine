import type { SessionType } from "@thai2d/shared";
import { config } from "../config";
import { deriveSessionFromInstant } from "../lib/session";
import { fetchJsonWithRetry } from "../lib/http";
import {
  ProviderError,
  type DataProvider,
  type FetchOptions,
  type RawResultRecord,
} from "./types";

/**
 * Primary public data provider: Thai Stock 2D community API.
 * Docs reference: https://api.thaistock2d.com  (/live, /2d_result, /2d_history)
 *
 * The upstream response format is parsed defensively: known field layouts are
 * mapped, and anything unrecognizable raises a ProviderError instead of being
 * silently fabricated into "data".
 */
export class Thai2DDataProvider implements DataProvider {
  readonly name = "thai2d";
  readonly isMock = false;
  private readonly base = config.thai2dBaseUrl.replace(/\/$/, "");
  private readonly headers: Record<string, string>;

  constructor() {
    this.headers = { Accept: "application/json" };
    if (config.thai2dApiKey) this.headers["Authorization"] = `Bearer ${config.thai2dApiKey}`;
  }

  async fetchLatest(): Promise<RawResultRecord[]> {
    // The /live endpoint reports the *provisional mid-session* number, which
    // is NOT the official result and changes every tick. Storing it as a
    // historical result corrupted recent days — so /live no longer produces
    // result rows. Final results come exclusively from /2d_result?date=...
    return [];
  }

  async fetchHistory(opts: FetchOptions = {}): Promise<RawResultRecord[]> {
    const out: RawResultRecord[] = [];
    const days = opts.days ?? 365;
    // Walk backwards day-by-day using the official per-date endpoint.
    // NOTE: despite docs showing DD-MM-YYYY, the live server expects
    // YYYY-MM-DD (verified 2026-08-25); DD-MM returns a SafeMySQL error body.
    // Single-day failures must not abort the whole historical import.
    for (let i = 0; i < days; i++) {
      const d = new Date();
      d.setUTCDate(d.getUTCDate() - i);
      const iso = d.toISOString().slice(0, 10);
      if (opts.toDate && iso > opts.toDate) continue;
      if (opts.fromDate && iso <= opts.fromDate) break;
      const dow = d.getUTCDay();
      if (dow === 0 || dow === 6) continue; // Thai SET closed Sat/Sun — no draws
      try {
        const res = await fetchJsonWithRetry(
          this.name,
          `${this.base}/2d_result?date=${iso}`,
          this.headers
        );
        out.push(...parseHistoryDay(this.name, iso, res.body));
      } catch (err) {
        console.warn(`[thai2d] no history for ${iso}:`, (err as Error).message);
      }
    }
    return out;
  }
}

/* ------------------------------------------------------------------ parsers */

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** Numbers arrive with thousands separators ("1,600.58") — strip safely. */
function numOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const s = String(v).replace(/,/g, "").trim();
  if (!s || s === "--") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function parseSessionLabel(v: unknown): SessionType | null {
  const s = String(v ?? "").toLowerCase();
  if (!s) return null;
  if (s.includes("12:") || s.includes("morning") || s === "m" || s.includes("am")) return "MORNING";
  if (s.includes("16:") || s.includes("4:3") || s.includes("evening") || s.includes("pm"))
    return "AFTERNOON";
  return null;
}

/**
 * Official draw slots (Bangkok wall clock): 11:00, 12:01, 15:00, 16:30.
 * User-facing Myanmar sessions map to the two FINAL draws:
 *   12:01 Bangkok -> MORNING   (occurs ~11:31 Asia/Yangon, before the
 *                               12:00 PM Yangon prediction cutoff)
 *   16:30 Bangkok -> AFTERNOON (~16:00 Asia/Yangon)
 * The 11:00 / 15:00 slots are intermediate SET readings, not stored as results.
 */
const SLOT_SESSION: Record<string, SessionType> = {
  "12:01": "MORNING",
  "16:30": "AFTERNOON",
};

function bangkokTs(dateStr: string, timeStr: string): string | undefined {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return undefined;
  const m = /(\d{1,2}):(\d{2})/.exec(timeStr ?? "");
  if (!m) return undefined;
  return `${dateStr}T${m[1].padStart(2, "0")}:${m[2]}:00+07:00`;
}

export function parseLivePayload(provider: string, body: unknown): RawResultRecord[] {
  const root = asRecord(body) ?? {};
  const out: RawResultRecord[] = [];

  // Finalized slots from today's `result` array (twod "--" = not drawn yet).
  const slots = Array.isArray(root["result"]) ? (root["result"] as unknown[]) : [];
  for (const item of slots) {
    const rec = asRecord(item);
    if (!rec) continue;
    const twod = rec["twod"];
    if (twod === undefined || twod === null || String(twod).trim() === "--") continue;
    const dateStr = String(rec["stock_date"] ?? "");
    const timeStr = String(rec["open_time"] ?? "");
    const session =
      SLOT_SESSION[timeStr.slice(0, 5)] ??
      parseSessionLabel(timeStr) ??
      deriveSessionFromInstant(bangkokTs(dateStr, timeStr) ?? `${dateStr}T04:00:00Z`).session;
    if (SLOT_SESSION[timeStr.slice(0, 5)] === undefined && timeStr.slice(0, 5) !== "16:30" &&
        timeStr.slice(0, 5) !== "12:01") {
      continue; // intermediate 11:00 / 15:00 readings are not stored as results
    }
    out.push({
      date: deriveSessionFromInstant(
        bangkokTs(dateStr, timeStr) ?? `${dateStr}T04:00:00Z`
      ).date,
      session,
      setValue: numOrNull(rec["set"]),
      marketValue: numOrNull(rec["value"]),
      twod: String(twod),
      sourceTimestampUtc: bangkokTs(dateStr, timeStr) ?? null,
    });
  }

  // Live snapshot (may be ahead of the last finalized slot).
  const inner = asRecord(root["live"]);
  if (inner) {
    const twod = inner["twod"];
    if (twod !== undefined && twod !== null && String(twod).trim() !== "--") {
      const dateStr = String(inner["date"] ?? String(root["server_time"] ?? "").slice(0, 10) ?? "");
      const timeFull = String(inner["time"] ?? ""); // "YYYY-MM-DD HH:MM:SS"
      const tDate = timeFull.slice(0, 10) || dateStr;
      const tTime = timeFull.slice(11) || "00:00";
      out.push({
        date: deriveSessionFromInstant(
          bangkokTs(tDate, tTime) ?? `${tDate}T04:00:00Z`
        ).date,
        session:
          SLOT_SESSION[tTime.slice(0, 5)] ??
          deriveSessionFromInstant(bangkokTs(tDate, tTime) ?? `${tDate}T04:00:00Z`).session,
        setValue: numOrNull(inner["set"]),
        marketValue: numOrNull(inner["value"]),
        twod: String(twod),
        sourceTimestampUtc: bangkokTs(tDate, tTime) ?? new Date().toISOString(),
      });
    }
  }

  if (out.length === 0) {
    throw new ProviderError(
      provider,
      `Unrecognized /live payload: ${JSON.stringify(body).slice(0, 300)}`
    );
  }
  return out;
}

/** Parse one day's `/2d_result` payload: {date, child:[{time,set,value,twod}]}. */
export function parseHistoryDay(
  provider: string,
  isoDate: string,
  body: unknown
): RawResultRecord[] {
  const days: unknown[] = Array.isArray(body) ? body : [body];
  const records: RawResultRecord[] = [];
  for (const dayItem of days) {
    const day = asRecord(dayItem);
    if (!day) continue;
    const dateStr = String(day["date"] ?? isoDate);
    const child = Array.isArray(day["child"]) ? (day["child"] as unknown[]) : [];
    for (const item of child) {
      const rec = asRecord(item);
      if (!rec) continue;
      const twod = rec["twod"];
      if (twod === undefined || twod === null || String(twod).trim() === "--") continue;
      const timeStr = String(rec["time"] ?? "");
      const slot = timeStr.slice(0, 5);
      const session = SLOT_SESSION[slot];
      if (!session) continue; // store only the two final draws
      const ts = bangkokTs(dateStr, timeStr);
      records.push({
        date: deriveSessionFromInstant(ts ?? `${dateStr}T04:00:00Z`).date,
        session,
        setValue: numOrNull(rec["set"]),
        marketValue: numOrNull(rec["value"]),
        twod: String(twod),
        sourceTimestampUtc: ts ?? null,
      });
    }
  }
  return records;
}
