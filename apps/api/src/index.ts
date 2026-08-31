import cors from "cors";
import express from "express";
import helmet from "helmet";
import { config } from "./config";
import { prisma } from "./db";
import { apiRateLimiter, basicAuth } from "./middleware/auth";
import { errorHandler, notFound } from "./middleware/errors";
import { adminRouter } from "./routes/admin";
import { backtestRouter, modelPerformanceHandler } from "./routes/backtest";
import { healthRouter } from "./routes/health";
import { predictionRouter } from "./routes/prediction";
import { resultsRouter } from "./routes/results";
import { syncRouter } from "./routes/sync";
import { reportEnvironment } from "./lib/envcheck";
import { startScheduler } from "./services/scheduler";

export function createApp(): express.Express {
  const app = express();

  app.use(helmet());
  app.use(
    cors({
      // Exact origins from CORS_ORIGINS plus any *.vercel.app deployment
      // (preview + production domains are unique per deploy).
      origin: (origin, cb) => {
        if (!origin) return cb(null, true); // server-to-server / same-origin
        if (config.corsOrigins.includes(origin)) return cb(null, true);
        try {
          if (new URL(origin).hostname.endsWith(".vercel.app")) return cb(null, true);
        } catch {
          /* fall through */
        }
        cb(new Error("Not allowed by CORS"));
      },
      methods: ["GET", "POST", "PATCH"],
      credentials: false,
    })
  );
  app.use(express.json({ limit: "2mb" }));
  app.use(apiRateLimiter());

  // Liveness probe — proves THIS backend is running. Touches nothing:
  // no database, no prediction engine, no external APIs.
  app.get("/health", (_req, res) => {
    res.json({ status: "ok" });
  });

  // Public read endpoints.
  app.use("/api/results", resultsRouter);
  app.use("/api/prediction", predictionRouter);
  app.use("/api/backtest", backtestRouter);
  app.use("/api/sync", syncRouter); // POSTs inside are basic-auth protected
  app.get("/api/model/performance", modelPerformanceHandler);
  app.use("/api/admin", basicAuth, adminRouter);
  app.use("/api", healthRouter);

  app.use(notFound);
  app.use(errorHandler);
  return app;
}

export async function startServer(): Promise<void> {
  const app = createApp();
  app.listen(config.port, () => {
    console.log(`[api] listening on :${config.port} (${config.nodeEnv})`);
    startScheduler();
  });
}

// Run directly: `tsx src/index.ts`
if (require.main === module) {
  if (!reportEnvironment()) {
    console.error("[api] aborting startup due to fatal environment issues.");
    process.exit(1);
  }
  // Resilient startup: a missing database must not prevent the API from
  // serving /health and cached/offline responses (MVP requirement).
  prisma
    .$connect()
    .then(() => console.log("[api] database connected"))
    .catch((err) => {
      console.warn(
        `[api] database unavailable — starting in DEGRADED mode: ${(err as Error).message.split("\n")[0]}`
      );
    })
    .then(startServer)
    .catch((err) => {
      console.error("[api] failed to start:", err);
      process.exit(1);
    });
}
