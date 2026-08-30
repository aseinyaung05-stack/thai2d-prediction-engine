/**
 * Timezone-aware time utilities.
 *
 * Canonical storage is UTC. User-facing sessions are defined in
 * Asia/Yangon; source market data originates in Asia/Bangkok.
 * NEVER add/subtract fixed hours — always use IANA zone conversions here.
 */
import {
  SESSIONS,
  SESSION_LOCAL_TIME,
  TIMEZONES,
  type SessionType,
} from "./types";

/** Format a Date into zone-local "YYYY-MM-DD". */
export function localDateInZone(date: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date); // en-CA yields YYYY-MM-DD
  return parts;
}

/** Zone-local wall-clock components of an instant. */
export function localPartsInZone(
  date: Date,
  timeZone: string
): { year: number; month: number; day: number; hour: number; minute: number; second: number } {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const parts: Record<string, string> = {};
  for (const p of dtf.formatToParts(date)) {
    if (p.type !== "literal") parts[p.type] = p.value;
  }
  let hour = parseInt(parts["hour"] ?? "0", 10);
  if (hour === 24) hour = 0; // some ICU versions emit 24:00
  return {
    year: parseInt(parts["year"] ?? "1970", 10),
    month: parseInt(parts["month"] ?? "1", 10),
    day: parseInt(parts["day"] ?? "1", 10),
    hour,
    minute: parseInt(parts["minute"] ?? "0", 10),
    second: parseInt(parts["second"] ?? "0", 10),
  };
}

/** Offset (ms) of `timeZone` at instant `date` such that utc + offset == local. */
export function zoneOffsetMs(date: Date, timeZone: string): number {
  const p = localPartsInZone(date, timeZone);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

/** Convert zone-local wall-clock time to the correct UTC instant. */
export function zonedWallTimeToUtc(
  y: number,
  m: number,
  d: number,
  hour: number,
  minute: number,
  timeZone: string
): Date {
  const guess = new Date(Date.UTC(y, m - 1, d, hour, minute));
  let offset = zoneOffsetMs(guess, timeZone);
  let result = new Date(guess.getTime() - offset);
  // Refine once to handle DST boundary edge cases (Yangon/Bangkok have no DST,
  // but keep this generic & correct).
  offset = zoneOffsetMs(result, timeZone);
  result = new Date(guess.getTime() - offset);
  return result;
}

/** Parse "YYYY-MM-DD" into components. */
export function parseISODate(s: string): { y: number; m: number; d: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!match) return null;
  const y = parseInt(match[1], 10);
  const m = parseInt(match[2], 10);
  const d = parseInt(match[3], 10);
  if (m < 1 || m > 12 || d < 1 || d > 31) return null;
  return { y, m, d };
}

/**
 * The exact UTC cutoff for a prediction session:
 * the Myanmar-local wall-clock moment the session's draw occurs.
 * Only source data with timestamp <= cutoff may be used by the model.
 */
export function sessionCutoffUtc(sessionDate: string, session: SessionType): Date {
  const parsed = parseISODate(sessionDate);
  if (!parsed) throw new Error(`Invalid session date: ${sessionDate}`);
  const { hour, minute } = SESSION_LOCAL_TIME[session];
  return zonedWallTimeToUtc(parsed.y, parsed.m, parsed.d, hour, minute, TIMEZONES.MYANMAR);
}

/** Current Myanmar-local date ("YYYY-MM-DD"). */
export function currentMyanmarDate(now: Date = new Date()): string {
  return localDateInZone(now, TIMEZONES.MYANMAR);
}

/** Which sessions remain today (Yangon), i.e. cutoff still in the future. */
export function upcomingSessions(now: Date = new Date()): SessionType[] {
  const d = currentMyanmarDate(now);
  return SESSIONS.filter((s) => sessionCutoffUtc(d, s).getTime() > now.getTime());
}

/** Next session to be drawn: {session, sessionDate, cutoffUtc}.
 *  Weekend-aware: Thai SET is closed Sat/Sun, so the next draw is always
 *  on a weekday (Mon 12:00 PM Yangon after Friday's afternoon session). */
export function nextSession(now: Date = new Date()): {
  session: SessionType;
  sessionDate: string;
  cutoffUtc: Date;
} {
  const today = currentMyanmarDate(now);
  const tp = parseISODate(today)!;
  const todayDow = new Date(Date.UTC(tp.y, tp.m - 1, tp.d)).getUTCDay();
  if (todayDow === 0 || todayDow === 6) {
    const [y, m, d] = nextYangonWeekday(today);
    const t = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    return { session: "MORNING", sessionDate: t, cutoffUtc: sessionCutoffUtc(t, "MORNING") };
  }
  for (const s of SESSIONS) {
    const cut = sessionCutoffUtc(today, s);
    if (cut.getTime() > now.getTime()) return { session: s, sessionDate: today, cutoffUtc: cut };
  }
  // All of today's sessions drawn -> next trading day's MORNING (Yangon calendar).
  const [y, m, d] = nextYangonWeekday(today);
  const t = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  return { session: "MORNING", sessionDate: t, cutoffUtc: sessionCutoffUtc(t, "MORNING") };
}

/** Roll a Yangon calendar date forward until it lands on a weekday. */
function nextYangonWeekday(iso: string): [number, number, number] {
  let [y, m, d] = nextYangonCalendarDay(iso);
  while (true) {
    const dow = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
    if (dow !== 0 && dow !== 6) return [y, m, d];
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + 1);
    y = dt.getUTCFullYear();
    m = dt.getUTCMonth() + 1;
    d = dt.getUTCDate();
  }
}

function nextYangonCalendarDay(iso: string): [number, number, number] {
  const p = parseISODate(iso)!;
  const dt = new Date(Date.UTC(p.y, p.m - 1, p.d));
  dt.setUTCDate(dt.getUTCDate() + 1);
  return [dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate()];
}

/** Human-readable Yangon time, e.g. "2026-08-23 14:05 MM". */
export function formatYangon(date: Date): string {
  const p = localPartsInZone(date, TIMEZONES.MYANMAR);
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)} MM`;
}
