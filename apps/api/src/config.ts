import "dotenv/config";

function num(name: string, def: number): number {
  const v = process.env[name];
  if (!v) return def;
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
}

function bool(name: string, def: boolean): boolean {
  const v = process.env[name];
  if (v === undefined) return def;
  return v === "true" || v === "1";
}

export const config = {
  nodeEnv: process.env.NODE_ENV ?? "development",
  isProduction: (process.env.NODE_ENV ?? "development") === "production",
  port: num("PORT", 4000),
  databaseUrl: process.env.DATABASE_URL ?? "",
  allowMockData: bool("ALLOW_MOCK_DATA", false),
  strictValidation: bool("STRICT_DATA_VALIDATION", true),

  activeProvider: process.env.DATA_PROVIDER ?? "thai2d",
  thai2dBaseUrl: process.env.THAI2D_API_BASE_URL ?? "https://api.thaistock2d.com",
  thai2dApiKey: process.env.THAI2D_API_KEY ?? "",
  setBaseUrl: process.env.SET_API_BASE_URL ?? "https://data-api.set.or.th",
  setApiKey: process.env.SET_API_KEY ?? "",

  syncIntervalMinutes: num("SYNC_INTERVAL_MINUTES", 10),
  httpTimeoutMs: num("HTTP_TIMEOUT_MS", 12000),
  httpMaxRetries: num("HTTP_MAX_RETRIES", 3),

  // Render's fromService.hostport yields "host:port" without a scheme;
  // normalize so fetch() always receives a valid absolute URL.
  predictionServiceUrl: (() => {
    const raw = process.env.PREDICTION_SERVICE_URL ?? "http://localhost:8000";
    return /^https?:\/\//.test(raw) ? raw : `http://${raw}`;
  })(),
  predictionApiToken: process.env.PREDICTION_API_TOKEN ?? "change-me-internal-token",

  adminUsername: process.env.ADMIN_USERNAME ?? "admin",
  adminPassword: process.env.ADMIN_PASSWORD ?? "",
  rateLimitWindowMs: num("API_RATE_LIMIT_WINDOW_MS", 60000),
  rateLimitMax: num("API_RATE_LIMIT_MAX", 120),
  corsOrigins: (process.env.CORS_ORIGINS ?? "http://localhost:3000")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
};
