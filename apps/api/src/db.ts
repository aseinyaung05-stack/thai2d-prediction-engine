import { PrismaClient } from "@prisma/client";

export const prisma = new PrismaClient();
export type { Result, PredictionRun, DataSyncLog, ModelVersion, Backtest } from "@prisma/client";
