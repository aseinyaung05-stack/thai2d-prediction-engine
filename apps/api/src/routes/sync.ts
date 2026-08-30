import { Router, text } from "express";
import { prisma } from "../db";
import { basicAuth } from "../middleware/auth";
import { ingestRecords, syncFromProvider } from "../services/ingest";
import { validateRawRecord } from "../services/validation";

export const syncRouter = Router();

/** POST /api/sync — manual "Sync Now" (admin). ?days=N limits history depth. */
syncRouter.post("/", basicAuth, async (req, res) => {
  const provider = typeof req.query.provider === "string" ? req.query.provider : undefined;
  const daysRaw = Number(req.query.days);
  const days = Number.isFinite(daysRaw) && daysRaw > 0 ? Math.min(400, Math.floor(daysRaw)) : undefined;
  try {
    const stats = await syncFromProvider("manual", provider, days);
    res.json({ ok: true, ...stats });
  } catch (err) {
    res.status(502).json({
      ok: false,
      error: "Data source unavailable — prediction may be stale.",
      detail: (err as Error).message,
    });
  }
});

/**
 * POST /api/import — CSV import (admin).
 * Body: text/csv with header: date,time,result[,set,value]
 *   date: YYYY-MM-DD (Myanmar-local session date)
 *   time: "12:01 PM" / "16:30" etc.
 */
syncRouter.post(
  "/import",
  basicAuth,
  text({ type: ["text/csv", "text/plain"], limit: "5mb" }),
  async (req, res) => {
    const body = typeof req.body === "string" ? req.body : "";
    if (!body.trim()) return res.status(400).json({ error: "Empty CSV body" });

    const lines = body.split(/\r?\n/).filter((l) => l.trim());
    if (!lines[0]?.toLowerCase().includes("date")) {
      return res
        .status(400)
        .json({ error: 'CSV must start with header "date,time,result[,set,value]"' });
    }

    const records = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(",").map((c) => c.trim());
      records.push({
        date: cols[0] ?? "",
        session: deriveCsvSession(cols[1] ?? ""),
        twod: cols[2] ?? "",
        setValue: cols[3] ? Number(cols[3]) : null,
        marketValue: cols[4] ? Number(cols[4]) : null,
        sourceTimestampUtc: null,
        source: "csv_import",
      });
    }

    const valid = [];
    let rejected = 0;
    const sampleErrors: string[] = [];
    for (let i = 0; i < records.length; i++) {
      const check = validateRawRecord(records[i]);
      if (!check.ok) {
        rejected++;
        if (sampleErrors.length < 20) sampleErrors.push(`line ${i + 2}: ${check.reason}`);
        continue;
      }
      valid.push(records[i]);
    }

    const stats = await ingestRecords(valid, { source: "csv_import" });
    await prisma.dataSyncLog.create({
      data: {
        startedAt: new Date(),
        finishedAt: new Date(),
        status: rejected > 0 ? "PARTIAL" : "SUCCESS",
        provider: "csv_import",
        trigger: "manual",
        recordsFetched: records.length,
        recordsInserted: stats.inserted,
        recordsSkipped: stats.skipped,
        recordsRejected: rejected,
        details: { sampleErrors },
      },
    });
    res.json({ ok: true, ...stats, sampleErrors });
  }
);

/** GET /api/sync/logs — recent sync audit trail (public read). */
syncRouter.get("/logs", async (_req, res, next) => {
  try {
    const logs = await prisma.dataSyncLog.findMany({ orderBy: { startedAt: "desc" }, take: 50 });
    res.json({ logs });
  } catch (err) {
    next(err);
  }
});

/** GET /api/sync/status — last successful sync timestamp (public read). */
syncRouter.get("/status", async (_req, res, next) => {
  try {
    const lastSuccess = await prisma.dataSyncLog.findFirst({
      where: { status: { in: ["SUCCESS", "PARTIAL"] } },
      orderBy: { startedAt: "desc" },
    });
    const lastAttempt = await prisma.dataSyncLog.findFirst({ orderBy: { startedAt: "desc" } });
    res.json({
      lastSuccessfulSync: lastSuccess?.finishedAt ?? null,
      lastAttempt: lastAttempt
        ? {
            at: lastAttempt.startedAt,
            status: lastAttempt.status,
            provider: lastAttempt.provider,
            inserted: lastAttempt.recordsInserted,
          }
        : null,
    });
  } catch (err) {
    next(err);
  }
});

function deriveCsvSession(time: string): string {
  const m = /(\d{1,2}):(\d{2})\s*(AM|PM)?/i.exec(time);
  if (!m) return "";
  let h = parseInt(m[1], 10);
  const ap = m[3]?.toUpperCase();
  if (ap === "PM" && h < 12) h += 12;
  if (ap === "AM" && h === 12) h = 0;
  return h < 15 ? "MORNING" : "AFTERNOON";
}
