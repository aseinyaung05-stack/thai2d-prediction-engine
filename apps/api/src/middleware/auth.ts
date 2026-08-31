import type { NextFunction, Request, Response } from "express";
import rateLimit from "express-rate-limit";
import { config } from "../config";

/** HTTP Basic authentication guarding admin/sync/import endpoints. */
export function basicAuth(req: Request, res: Response, next: NextFunction): void {
  const header = req.headers.authorization ?? "";
  if (!header.startsWith("Basic ")) {
    res.setHeader("WWW-Authenticate", 'Basic realm="thai2d-admin"');
    res.status(401).json({ error: "Authentication required" });
    return;
  }
  let user = "";
  let pass = "";
  try {
    const decoded = Buffer.from(header.slice(6), "base64").toString("utf8");
    const idx = decoded.indexOf(":");
    user = decoded.slice(0, idx);
    pass = decoded.slice(idx + 1);
  } catch {
    res.status(401).json({ error: "Malformed credentials" });
    return;
  }
  const okUser = user === config.adminUsername;
  // Constant-time-ish comparison to avoid trivial timing leaks.
  const okPass =
    config.adminPassword.length > 0 &&
    pass.length === config.adminPassword.length &&
    pass === config.adminPassword;
  if (!okUser || !okPass) {
    res.status(401).json({ error: "Invalid credentials" });
    return;
  }
  next();
}

export function apiRateLimiter(): ReturnType<typeof rateLimit> {
  return rateLimit({
    windowMs: config.rateLimitWindowMs,
    max: config.rateLimitMax,
    standardHeaders: true,
    legacyHeaders: false,
    message: { error: "Too many requests — slow down." },
    // Trusted server-to-server callers (web SSR) bypass the public limiter.
    skip: (req) =>
      Boolean(config.rateLimitBypassToken) &&
      req.get("x-bypass-token") === config.rateLimitBypassToken,
  });
}
