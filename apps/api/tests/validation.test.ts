import { describe, expect, it } from "vitest";
import { rawRecordHash } from "../src/services/ingest";
import { validateRawRecord } from "../src/services/validation";

const base = {
  date: "2026-08-23",
  session: "MORNING",
  twod: "01",
  sourceTimestampUtc: "2026-08-23T05:00:00.000Z",
};

describe("raw record validation", () => {
  it("accepts a valid record", () => {
    expect(validateRawRecord(base)).toMatchObject({ ok: true });
  });

  it("rejects bad dates", () => {
    expect(validateRawRecord({ ...base, date: "23-08-2026" }).ok).toBe(false);
    expect(validateRawRecord({ ...base, date: "2026-13-40" }).ok).toBe(false);
  });

  it("rejects invalid sessions", () => {
    expect(validateRawRecord({ ...base, session: "EVENING" }).ok).toBe(false);
  });

  it("rejects invalid 2D values", () => {
    expect(validateRawRecord({ ...base, twod: "100" }).ok).toBe(false);
    expect(validateRawRecord({ ...base, twod: "xy" }).ok).toBe(false);
  });

  it("rejects future timestamps (leakage/corruption guard)", () => {
    const future = new Date(Date.now() + 24 * 3600_000).toISOString();
    expect(validateRawRecord({ ...base, sourceTimestampUtc: future }).ok).toBe(false);
  });
});

describe("duplicate detection hash", () => {
  it("is stable for identical records", () => {
    expect(rawRecordHash(base)).toBe(rawRecordHash({ ...base }));
  });

  it("differs across sessions and values", () => {
    expect(rawRecordHash(base)).not.toBe(rawRecordHash({ ...base, session: "AFTERNOON" }));
    expect(rawRecordHash(base)).not.toBe(rawRecordHash({ ...base, twod: "02" }));
  });
});
