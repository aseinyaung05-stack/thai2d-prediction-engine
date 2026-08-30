import {
  currentMyanmarDate,
  localDateInZone,
  localPartsInZone,
  normalizeTwod,
  splitDigits,
  TIMEZONES,
  type SessionType,
} from "@thai2d/shared";
import type { RawResultRecord } from "../providers/types";

/**
 * Map a source-market instant to the Myanmar-local prediction session.
 *
 * Thai source events occur in Asia/Bangkok; user sessions are defined in
 * Asia/Yangon. We convert with IANA zones and classify by Yangon wall clock:
 *   hour < 15  -> MORNING (12:00 PM session)
 *   hour >= 15 -> AFTERNOON (4:30 PM session)
 */
export function deriveSessionFromInstant(
  isoTimestamp: string
): { date: string; session: SessionType } {
  const d = new Date(isoTimestamp);
  if (Number.isNaN(d.getTime())) throw new Error(`Invalid timestamp: ${isoTimestamp}`);
  const p = localPartsInZone(d, TIMEZONES.MYANMAR);
  const date = `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
  const session: SessionType = p.hour < 15 ? "MORNING" : "AFTERNOON";
  return { date, session };
}

/** Strict validation of a raw record before it may touch the database. */
export function validateRawRecord(rec: RawResultRecord): { ok: true } | { ok: false; reason: string } {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(rec.date)) return { ok: false, reason: `bad date: ${rec.date}` };
  if (rec.session !== "MORNING" && rec.session !== "AFTERNOON")
    return { ok: false, reason: `bad session: ${String(rec.session)}` };
  const twod = normalizeTwod(rec.twod);
  if (!twod) return { ok: false, reason: `invalid 2D value: ${String(rec.twod)}` };
  try {
    splitDigits(twod);
  } catch {
    return { ok: false, reason: `digit split failed for ${twod}` };
  }
  if (
    rec.setValue !== null &&
    (typeof rec.setValue !== "number" || !Number.isFinite(rec.setValue))
  )
    return { ok: false, reason: "invalid set value" };
  if (
    rec.marketValue !== null &&
    (typeof rec.marketValue !== "number" || !Number.isFinite(rec.marketValue))
  )
    return { ok: false, reason: "invalid market value" };

  // Future timestamps are rejected — data must be historical/realized.
  if (rec.sourceTimestampUtc) {
    const t = new Date(rec.sourceTimestampUtc);
    if (Number.isNaN(t.getTime())) return { ok: false, reason: "invalid source timestamp" };
    if (t.getTime() > Date.now() + 5 * 60_000)
      return { ok: false, reason: `future source timestamp: ${rec.sourceTimestampUtc}` };
  }
  return { ok: true };
}

/** Convenience: today's Yangon date for sync windows. */
export function todayYangon(): string {
  return currentMyanmarDate(new Date());
}

export { localDateInZone };
