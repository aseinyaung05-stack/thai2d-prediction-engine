import { config } from "../config";
import { MockDataProvider } from "./mock";
import { SetDataProvider } from "./set";
import { Thai2DDataProvider } from "./thai2d";
import type { DataProvider } from "./types";

export const PROVIDERS: Record<string, () => DataProvider> = {
  thai2d: () => new Thai2DDataProvider(),
  set: () => new SetDataProvider(),
  mock: () => new MockDataProvider(),
};

/** Instantiate a provider by name (default = configured active provider). */
export function getProvider(name?: string): DataProvider {
  const key = name ?? config.activeProvider;
  const factory = PROVIDERS[key];
  if (!factory) throw new Error(`Unknown data provider: ${key}`);
  const provider = factory();
  if (provider.isMock && config.isProduction && !config.allowMockData) {
    throw new Error("Mock provider is not allowed in production mode.");
  }
  return provider;
}

export * from "./types";
