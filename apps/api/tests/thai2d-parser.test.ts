/**
 * Offline parser tests against REAL payloads captured from the documented
 * API (https://docs.thaistock2d.com). No network access required.
 */
import { describe, expect, it } from "vitest";
import { parseHistoryDay, parseLivePayload } from "../src/providers/thai2d";

// Captured 2026-08-24 from https://api.thaistock2d.com/live
const LIVE_SAMPLE = {
  server_time: "2026-08-24 11:19:26",
  live: {
    set: "1,600.58",
    value: "32,483.19",
    time: "2026-08-24 11:19:26",
    twod: "83",
    date: "2026-08-24",
  },
  result: [
    {
      set: "1,599.45",
      value: "31,528.24",
      open_time: "11:00:00",
      twod: "58",
      stock_date: "2026-08-24",
      stock_datetime: "2026-08-24 11:00:00",
      history_id: "2760920",
    },
    {
      set: "--",
      value: "--",
      open_time: "12:01:00",
      twod: "--",
      stock_date: "2026-08-24",
      stock_datetime: "2026-08-24 11:19:26",
      history_id: null,
    },
    {
      set: "--",
      value: "--",
      open_time: "15:00:00",
      twod: "--",
      stock_date: "2026-08-24",
      stock_datetime: "2026-08-24 11:19:26",
      history_id: null,
    },
    {
      set: "--",
      value: "--",
      open_time: "16:30:00",
      twod: "--",
      stock_date: "2026-08-24",
      stock_datetime: "2026-08-24 11:19:26",
      history_id: null,
    },
  ],
  holiday: { status: "2", date: "2026-08-24", name: "NULL" },
};

// Documented /2d_result day shape
const HISTORY_SAMPLE = [
  {
    date: "2026-08-21",
    child: [
      { time: "11:00:00", set: "1,621.05", value: "27,982.10", twod: "52" },
      { time: "12:01:00", set: "1,622.89", value: "35,908.91", twod: "47" },
      { time: "15:00:00", set: "1,622.37", value: "67,016.57", twod: "76" },
      { time: "16:30:00", set: "1,626.27", value: "85,650.24", twod: "70" },
    ],
  },
];

describe("thai2d provider parsers (offline, real schemas)", () => {
  it("parses /live: skips intermediate slots, keeps live snapshot, strips commas", () => {
    const recs = parseLivePayload("thai2d", LIVE_SAMPLE);
    // 11:00 is an intermediate reading -> skipped; 12:01/15:00/16:30 are "--".
    // Only the live snapshot qualifies.
    const morning = recs.filter((r) => r.session === "MORNING");
    expect(morning.length).toBeGreaterThanOrEqual(1);
    const live = recs.find((r) => r.twod === "83")!;
    expect(live).toBeDefined();
    expect(live.setValue).toBeCloseTo(1600.58); // comma stripped
    expect(live.marketValue).toBeCloseTo(32483.19);
    // 11:19 Bangkok = 10:49 Yangon -> MORNING stream
    expect(live.session).toBe("MORNING");
    expect(live.sourceTimestampUtc).toContain("+07:00");
    // The finalized 11:00 slot must NOT be stored as a result:
    expect(recs.find((r) => r.twod === "58")).toBeUndefined();
  });

  it("maps official slots: 12:01->MORNING, 16:30->AFTERNOON, skips 11:00/15:00", () => {
    const recs = parseHistoryDay("thai2d", "2026-08-21", HISTORY_SAMPLE);
    expect(recs.map((r) => r.session).sort()).toEqual(["AFTERNOON", "MORNING"]);
    const morning = recs.find((r) => r.session === "MORNING")!;
    const afternoon = recs.find((r) => r.session === "AFTERNOON")!;
    expect(morning.twod).toBe("47");
    expect(afternoon.twod).toBe("70");
    expect(afternoon.setValue).toBeCloseTo(1626.27);
  });

  it("rejects unrecognized payloads instead of fabricating data", () => {
    expect(() => parseLivePayload("thai2d", { hello: "world" })).toThrow();
  });

  it("handles '--' (not drawn) gracefully", () => {
    const empty = parseHistoryDay("thai2d", "2026-08-24", [
      { date: "2026-08-24", child: [{ time: "16:30:00", set: "--", value: "--", twod: "--" }] },
    ]);
    expect(empty).toEqual([]);
  });
});
