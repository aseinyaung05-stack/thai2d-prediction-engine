/**
 * 2D normalization + section classification.
 *
 * CRITICAL RULE: results are two-character zero-padded strings internally.
 * "01" must NEVER become the number 1 in storage or display.
 */
import { SECTION_RANGE, SECTIONS, type SectionId } from "./types";

/** Returns true when `value` is an integer 0-99. */
export function isValidNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 99;
}

/**
 * Normalize any reasonable representation ("1", 1, "01", 99) into a
 * zero-padded 2-char string. Returns null when invalid (not 0-99).
 */
export function normalizeTwod(input: string | number | null | undefined): string | null {
  if (input === null || input === undefined) return null;
  const raw = String(input).trim();
  if (!/^\d{1,2}$/.test(raw)) return null;
  const n = parseInt(raw, 10);
  if (!isValidNumber(n)) return null;
  return n.toString().padStart(2, "0");
}

/** Split a normalized twod string into tens / ones digits. */
export function splitDigits(twod: string): { tens: number; ones: number } {
  const norm = normalizeTwod(twod);
  if (!norm) throw new Error(`Invalid 2D value: ${twod}`);
  return { tens: parseInt(norm[0], 10), ones: parseInt(norm[1], 10) };
}

/** Digit sum of a number 0-99 (e.g. "59" -> 14). */
export function digitSum(n: number): number {
  const t = Math.floor(n / 10);
  const o = n % 10;
  return t + o;
}

/** Classify a number 0-99 into its section. Throws on invalid input. */
export function classifySection(n: number): SectionId {
  if (!isValidNumber(n)) throw new Error(`Out of range: ${n}`);
  for (const s of SECTIONS) {
    const { min, max } = SECTION_RANGE[s];
    if (n >= min && n <= max) return s;
  }
  throw new Error(`Unreachable: ${n}`);
}

/** Section of a normalized twod string. */
export function sectionOfTwod(twod: string): SectionId {
  return classifySection(parseInt(twod, 10));
}

/** Reverse of a number, e.g. 12 <-> 21, 80 <-> 08. */
export function reverseNumber(n: number): number {
  if (!isValidNumber(n)) throw new Error(`Out of range: ${n}`);
  const tens = Math.floor(n / 10);
  const ones = n % 10;
  return ones * 10 + tens;
}

/** All numbers belonging to a section. */
export function sectionNumbers(section: SectionId): number[] {
  const { min, max } = SECTION_RANGE[section];
  const out: number[] = [];
  for (let i = min; i <= max; i++) out.push(i);
  return out;
}
