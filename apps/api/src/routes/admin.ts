import { Router } from "express";
import { Prisma } from "@prisma/client";
import { normalizeTwod } from "@thai2d/shared";
import { prisma } from "../db";
import { computeDataQuality } from "../services/quality";

export const adminRouter = Router();

/** GET /api/admin/data-quality */
adminRouter.get("/data-quality", async (_req, res, next) => {
  try {
    res.json(await computeDataQuality());
  } catch (err) {
    next(err);
  }
});

/** GET /api/admin/duplicates — true duplicates (date+session+twod). */
adminRouter.get("/duplicates", async (_req, res, next) => {
  try {
    const rows = await prisma.result.groupBy({
      by: ["date", "session", "twod"],
      _count: { _all: true },
      having: { twod: { _count: { gte: 2 } } },
      orderBy: [{ date: "desc" }],
      take: 200,
    });
    res.json({ count: rows.length, duplicates: rows });
  } catch (err) {
    next(err);
  }
});

/** GET /api/admin/missing-dates — trading days (last 90d) lacking a session. */
adminRouter.get("/missing-dates", async (_req, res, next) => {
  try {
    const since = new Date(Date.now() - 90 * 24 * 3600_000);
    const grouped = await prisma.result.groupBy({
      by: ["date"],
      where: { date: { gte: since } },
      _count: { session: true },
      orderBy: [{ date: "desc" }],
    });
    const missing: Array<{ date: string; presentSessions: number }> = [];
    for (const g of grouped) {
      const dow = new Date(g.date).getUTCDay();
      if (dow === 0 || dow === 6) continue; // weekend: no draws
      if ((g._count.session ?? 0) < 2)
        missing.push({
          date: g.date.toISOString().slice(0, 10),
          presentSessions: g._count.session ?? 0,
        });
    }
    missing.sort((a, b) => b.date.localeCompare(a.date));
    res.json({ count: missing.length, missing });
  } catch (err) {
    next(err);
  }
});

/** GET /api/admin/errors — recent failed/partial syncs. */
adminRouter.get("/errors", async (_req, res, next) => {
  try {
    const logs = await prisma.dataSyncLog.findMany({
      where: { status: { in: ["FAILED", "PARTIAL"] } },
      orderBy: { startedAt: "desc" },
      take: 50,
    });
    res.json({ count: logs.length, errors: logs });
  } catch (err) {
    next(err);
  }
});

/** PATCH /api/admin/results/:id — correct an incorrect record (audited). */
adminRouter.patch("/results/:id", async (req, res, next) => {
  try {
    const { twod, setValue, marketValue } = req.body as {
      twod?: string;
      setValue?: number;
      marketValue?: number;
    };
    const existing = await prisma.result.findUnique({ where: { id: req.params.id } });
    if (!existing) return res.status(404).json({ error: "Record not found" });

    const data: Record<string, unknown> = {};
    if (twod !== undefined) {
      const norm = normalizeTwod(twod);
      if (!norm) return res.status(400).json({ error: "twod must be 00-99" });
      data.twod = norm;
      data.digitTens = parseInt(norm[0], 10);
      data.digitOnes = parseInt(norm[1], 10);
    }
    if (setValue !== undefined) {
      if (!Number.isFinite(setValue) || setValue < 0)
        return res.status(400).json({ error: "invalid setValue" });
      data.setValue = setValue;
    }
    if (marketValue !== undefined) {
      if (!Number.isFinite(marketValue) || marketValue < 0)
        return res.status(400).json({ error: "invalid marketValue" });
      data.marketValue = marketValue;
    }
    if (Object.keys(data).length === 0)
      return res.status(400).json({ error: "No editable fields supplied" });

    const updated = await prisma.result.update({
      where: { id: req.params.id },
      data,
    });
    // Audit entry.
    await prisma.dataSyncLog.create({
      data: {
        startedAt: new Date(),
        finishedAt: new Date(),
        status: "SUCCESS",
        provider: "manual_edit",
        trigger: "manual",
        details: { editedId: req.params.id, changes: data, before: { twod: existing.twod } } as Prisma.InputJsonValue,
      },
    });
    res.json({ ok: true, result: updated });
  } catch (err) {
    next(err);
  }
});
