import { describe, expect, it } from "vitest";
import {
  classifySection,
  normalizeTwod,
  reverseNumber,
  sectionNumbers,
  splitDigits,
} from "../src/normalize";
import {
  formatYangon,
  nextSession,
  sessionCutoffUtc,
  zonedWallTimeToUtc,
} from "../src/time";

describe("2D normalization", () => {
  it("zero-pads single digits and never converts '01' to '1'", () => {
    expect(normalizeTwod("01")).toBe("01");
    expect(normalizeTwod(1)).toBe("01");
    expect(normalizeTwod("1")).toBe("01");
    expect(normalizeTwod(99)).toBe("99");
    expect(normalizeTwod("00")).toBe("00");
  });

  it("rejects invalid values", () => {
    expect(normalizeTwod("100")).toBeNull();
    expect(normalizeTwod(-3)).toBeNull();
    expect(normalizeTwod("ab")).toBeNull();
    expect(normalizeTwod(null)).toBeNull();
    expect(normalizeTwod("1.5")).toBeNull();
  });

  it("splits digits", () => {
    expect(splitDigits("01")).toEqual({ tens: 0, ones: 1 });
    expect(splitDigits("59")).toEqual({ tens: 5, ones: 9 });
  });
});

describe("section classification", () => {
  it("classifies boundary values correctly", () => {
    expect(classifySection(0)).toBe("A");
    expect(classifySection(24)).toBe("A");
    expect(classifySection(25)).toBe("B");
    expect(classifySection(49)).toBe("B");
    expect(classifySection(50)).toBe("C");
    expect(classifySection(74)).toBe("C");
    expect(classifySection(75)).toBe("D");
    expect(classifySection(99)).toBe("D");
  });

  it("rejects out-of-range numbers", () => {
    expect(() => classifySection(100)).toThrow();
    expect(() => classifySection(-1)).toThrow();
  });

  it("each section has exactly 25 numbers", () => {
    for (const s of ["A", "B", "C", "D"] as const) {
      expect(sectionNumbers(s).length).toBe(25);
    }
  });
});

describe("reverse pairs", () => {
  it("reverses numbers including zero-padded cases", () => {
    expect(reverseNumber(12)).toBe(21);
    expect(reverseNumber(37)).toBe(73);
    expect(reverseNumber(80)).toBe(8); // 08 <-> 80
    expect(reverseNumber(8)).toBe(80);
  });
});

describe("timezone handling", () => {
  it("converts Myanmar wall time to UTC using IANA zone (UTC+6:30)", () => {
    const utc = zonedWallTimeToUtc(2026, 8, 23, 12, 0, "Asia/Yangon");
    expect(utc.toISOString()).toBe("2026-08-23T05:30:00.000Z");
    const utc2 = zonedWallTimeToUtc(2026, 8, 23, 16, 30, "Asia/Yangon");
    expect(utc2.toISOString()).toBe("2026-08-23T10:00:00.000Z");
  });

  it("session cutoffs match Yangon session times", () => {
    expect(sessionCutoffUtc("2026-08-23", "MORNING").toISOString()).toBe(
      "2026-08-23T05:30:00.000Z"
    );
    expect(sessionCutoffUtc("2026-08-23", "AFTERNOON").toISOString()).toBe(
      "2026-08-23T10:00:00.000Z"
    );
  });

  it("formats Yangon display time", () => {
    const d = new Date("2026-08-23T06:45:00.000Z");
    expect(formatYangon(d)).toBe("2026-08-23 13:15 MM");
  });

  it("next session rolls over to tomorrow MORNING after last cutoff", () => {
    const late = new Date("2026-08-23T11:00:00.000Z"); // 17:30 Yangon
    const nxt = nextSession(late);
    expect(nxt.session).toBe("MORNING");
    expect(nxt.sessionDate).toBe("2026-08-24");
    expect(nxt.cutoffUtc.toISOString()).toBe("2026-08-24T05:30:00.000Z");
  });
});

describe("weekend handling (SET closed Sat/Sun)", () => {
  it("Saturday evening rolls to MONDAY 12:00 PM", () => {
    const sat = new Date("2026-08-29T11:00:00.000Z"); // 17:30 Yangon Saturday
    const nxt = nextSession(sat);
    expect(nxt.session).toBe("MORNING");
    expect(nxt.sessionDate).toBe("2026-08-31"); // Monday
    expect(nxt.cutoffUtc.toISOString()).toBe("2026-08-31T05:30:00.000Z");
  });

  it("Sunday midday rolls to Monday morning", () => {
    const sun = new Date("2026-08-30T04:00:00.000Z"); // 10:30 Yangon Sunday
    const nxt = nextSession(sun);
    expect(nxt.sessionDate).toBe("2026-08-31");
  });
});
