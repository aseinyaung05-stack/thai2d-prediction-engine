import { config } from "../config";
import { ProviderError } from "../providers/types";

export interface FetchResult {
  ok: boolean;
  status: number;
  body: unknown;
  url: string;
}

/**
 * Production HTTP client for external data providers.
 *
 * Guarantees:
 *  - timeout protection (AbortController, HTTP_TIMEOUT_MS, default 12s)
 *  - bounded retries with exponential backoff (HTTP_MAX_RETRIES, default 3)
 *  - HTTP status validation (4xx short-circuits; 5xx/429 retry)
 *  - malformed JSON rejected explicitly (never parsed into fake records)
 *  - connection errors surfaced as ProviderError with full context
 */
export async function fetchJsonWithRetry(
  providerName: string,
  url: string,
  headers: Record<string, string> = {}
): Promise<FetchResult> {
  let lastErr: unknown = null;

  for (let attempt = 1; attempt <= config.httpMaxRetries; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.httpTimeoutMs);
    try {
      const res = await fetch(url, { signal: controller.signal, headers });
      clearTimeout(timer);

      if (!res.ok) {
        lastErr = new ProviderError(providerName, `HTTP ${res.status} for ${url}`);
        console.warn(
          `[${providerName}] attempt ${attempt}/${config.httpMaxRetries} failed: HTTP ${res.status} ${url}`
        );
        // Client errors (except 429 rate-limit) will not improve on retry.
        if (res.status >= 400 && res.status < 500 && res.status !== 429) {
          return { ok: false, status: res.status, body: null, url };
        }
      } else {
        // Malformed JSON handling: reject loudly instead of inventing data.
        let body: unknown;
        try {
          body = await res.json();
        } catch (parseErr) {
          console.error(`[${providerName}] malformed JSON from ${url}:`, (parseErr as Error).message);
          throw new ProviderError(providerName, `Malformed JSON response from ${url}`, parseErr);
        }
        return { ok: true, status: res.status, body, url };
      }
    } catch (err) {
      clearTimeout(timer);
      if (err instanceof ProviderError) throw err; // malformed JSON: do not retry
      lastErr = err;
      const reason =
        err instanceof Error && err.name === "AbortError"
          ? `timeout after ${config.httpTimeoutMs}ms`
          : (err as Error).message;
      console.warn(`[${providerName}] attempt ${attempt}/${config.httpMaxRetries} network error: ${reason}`);
    }

    if (attempt < config.httpMaxRetries) {
      await new Promise((r) => setTimeout(r, 500 * Math.pow(2, attempt - 1)));
    }
  }

  throw new ProviderError(
    providerName,
    `All ${config.httpMaxRetries} attempts failed for ${url}`,
    lastErr
  );
}
