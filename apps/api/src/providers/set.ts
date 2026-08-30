import { config } from "../config";
import { fetchJsonWithRetry } from "../lib/http";
import { ProviderError, type DataProvider, type FetchOptions, type RawResultRecord } from "./types";

/**
 * Official SET (Stock Exchange of Thailand) market-data provider.
 *
 * Authoritative source when a licensed API key is configured. SET's licensed
 * endpoints require credentials and have specific terms — this provider is
 * intentionally conservative: without SET_API_KEY it reports itself as
 * unavailable rather than guessing endpoint shapes.
 */
export class SetDataProvider implements DataProvider {
  readonly name = "set";
  readonly isMock = false;
  private readonly base = config.setBaseUrl.replace(/\/$/, "");

  get available(): boolean {
    return Boolean(config.setApiKey);
  }

  private requireKey(): void {
    if (!this.available) {
      throw new ProviderError(
        this.name,
        "SET_API_KEY not configured — official SET provider unavailable. " +
          "Configure a licensed key or use the thai2d/mock provider."
      );
    }
  }

  async fetchLatest(): Promise<RawResultRecord[]> {
    this.requireKey();
    const res = await fetchJsonWithRetry(
      this.name,
      `${this.base}/market/set/index/latest`,
      { Authorization: `Bearer ${config.setApiKey}`, Accept: "application/json" }
    );
    return mapSetIndexSnapshot(this.name, res.body);
  }

  async fetchHistory(_opts: FetchOptions = {}): Promise<RawResultRecord[]> {
    // Licensed historical SET series requires the exact contracted endpoint.
    // Intentionally unimplemented until real credentials + docs are supplied;
    // we refuse instead of fabricating history.
    this.requireKey();
    throw new ProviderError(
      this.name,
      "Historical import via official SET API requires your licensed endpoint spec. " +
        "Set SET_HISTORY_ENDPOINT or use thai2d for history."
    );
  }
}

/**
 * Map an index snapshot into raw records. Only maps fields that exist; throws
 * when the payload lacks the minimum required fields (index value + time).
 */
export function mapSetIndexSnapshot(provider: string, body: unknown): RawResultRecord[] {
  const root =
    body && typeof body === "object" && !Array.isArray(body)
      ? (body as Record<string, unknown>)
      : {};
  const idx = (root["index"] ?? root["data"] ?? root) as Record<string, unknown>;
  const value = Number(idx["value"] ?? idx["last"] ?? idx["SET"]);
  const ts = String(root["timestamp"] ?? idx["time"] ?? "");
  if (!Number.isFinite(value) || !ts) {
    throw new ProviderError(provider, `Unrecognized SET snapshot: ${JSON.stringify(body).slice(0, 300)}`);
  }
  return [
    {
      date: ts.slice(0, 10),
      session: "AFTERNOON",
      setValue: value,
      marketValue: value,
      twod: "", // SET alone does not define the draw number; ingestion pairs it.
      sourceTimestampUtc: ts,
    },
  ];
}
