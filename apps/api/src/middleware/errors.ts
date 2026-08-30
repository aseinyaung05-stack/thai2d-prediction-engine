import type { NextFunction, Request, Response } from "express";

export function errorHandler(err: Error, _req: Request, res: Response, _next: NextFunction): void {
  console.error("[api] error:", err.message);
  res.status(500).json({ error: "Internal server error", detail: err.message });
}

export function notFound(_req: Request, res: Response): void {
  res.status(404).json({ error: "Not found" });
}
