import { normalizeTwod } from "@thai2d/shared";

/**
 * Minimal structural shape any candidate record must expose before
 * validation. Providers/CSV importers adapt their native formats to this.
 */
export interface RawResultRecordLike {
  date: string;
  session: string;
  twod: string | number;
  setValue?: number | null;
  marketValue?: number | null;
  sourceTimestampUtc?: string | null;
  source?: string;
}

/** Strict validation used by both API sync and CSV import. */
export function validateRawRecord(
  rec: RawResultRecordLike
): { ok: true; twod: string } | { ok: false; reason: string } {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(rec.date)) return { ok: false, reason: `bad date: ${rec.date}` };
  const d = new Date(`${rec.date}T00:00:00.000Z`);
  if (Number.isNaN(d.getTime())) return { ok: false, reason: `unreal date: ${rec.date}` };
  if (rec.session !== "MORNING" && rec.session !== "AFTERNOON")
    return { ok: false, reason: `bad session: ${String(rec.session)}` };
  const twod = normalizeTwod(rec.twod);
  if (!twod) return { ok: false, reason: `invalid 2D value: ${String(rec.twod)}` };
  for (const [name, v] of [
    ["set", rec.setValue],
    ["market", rec.marketValue],
  ] as const) {
    if (v !== null && v !== undefined && (!Number.isFinite(Number(v)) || Number(v) < 0))
      return { ok: false, reason: `invalid ${name} value` };
  }
  if (rec.sourceTimestampUtc) {
    const t = new Date(rec.sourceTimestampUtc);
    if (Number.isNaN(t.getTime()))
      return { ok: false, reason: "invalid source timestamp" };
    if (t.getTime() > Date.now() + 5 * 60_000)
      return { ok: false, reason: `future source timestamp: ${rec.sourceTimestampUtc}` };
  }
  return { ok: true, twod };
}
