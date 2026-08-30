import { config } from "../config";

export interface EnvIssue {
  variable: string;
  severity: "FATAL" | "WARNING";
  message: string;
}

/**
 * Startup environment validation. Reports missing/misconfigured variables
 * WITHOUT ever printing secret values (STEP 4).
 */
export function validateEnvironment(): { fatal: EnvIssue[]; warnings: EnvIssue[] } {
  const fatal: EnvIssue[] = [];
  const warnings: EnvIssue[] = [];
  const has = (v: string | undefined | null) => Boolean(v && String(v).trim().length > 0);

  // --- database -------------------------------------------------------------
  if (!has(config.databaseUrl)) {
    fatal.push({
      variable: "DATABASE_URL",
      severity: "FATAL",
      message: "DATABASE_URL is not configured — the API cannot start.",
    });
  }

  // --- security ---------------------------------------------------------------
  if (!has(process.env.ADMIN_PASSWORD) || process.env.ADMIN_PASSWORD === "change-me-now") {
    if (config.isProduction) {
      fatal.push({
        variable: "ADMIN_PASSWORD",
        severity: "FATAL",
        message: "ADMIN_PASSWORD is missing or still the default value in production.",
      });
    } else {
      warnings.push({
        variable: "ADMIN_PASSWORD",
        severity: "WARNING",
        message: "ADMIN_PASSWORD not set (dev default active) — admin endpoints unprotected.",
      });
    }
  }
  if (!has(process.env.PREDICTION_API_TOKEN) || process.env.PREDICTION_API_TOKEN === "change-me-internal-token") {
    warnings.push({
      variable: "PREDICTION_API_TOKEN",
      severity: "WARNING",
      message: "PREDICTION_API_TOKEN not customized — internal service calls use the default.",
    });
  }

  // --- data provider ----------------------------------------------------------
  const provider = config.activeProvider;
  if (provider === "thai2d") {
    if (!has(config.thai2dApiKey)) {
      warnings.push({
        variable: "THAI2D_API_KEY",
        severity: "WARNING",
        message:
          "THAI2D_API_KEY is not configured — requests proceed without authentication; " +
          "the upstream API may rate-limit or reject them.",
      });
    }
    if (!has(config.thai2dBaseUrl)) {
      fatal.push({
        variable: "THAI2D_API_BASE_URL",
        severity: "FATAL",
        message: "THAI2D_API_BASE_URL is not configured and no default is safe to assume.",
      });
    }
  } else if (provider === "set") {
    if (!has(config.setApiKey)) {
      fatal.push({
        variable: "SET_API_KEY",
        severity: "FATAL",
        message: "DATA_PROVIDER=set requires SET_API_KEY (official/licensed access).",
      });
    }
  } else if (provider === "mock") {
    if (config.isProduction) {
      fatal.push({
        variable: "DATA_PROVIDER",
        severity: "FATAL",
        message: "Mock data provider cannot be active in production mode.",
      });
    } else {
      warnings.push({
        variable: "DATA_PROVIDER",
        severity: "WARNING",
        message: "MOCK/TEST MODE: records will be marked MOCK — never use for production analysis.",
      });
    }
  } else {
    fatal.push({ variable: "DATA_PROVIDER", severity: "FATAL", message: `Unknown provider "${provider}".` });
  }

  if (config.isProduction && config.allowMockData) {
    fatal.push({
      variable: "ALLOW_MOCK_DATA",
      severity: "FATAL",
      message: "ALLOW_MOCK_DATA=true is forbidden in production mode.",
    });
  }

  return { fatal, warnings };
}

/** Log issues at startup; returns false when the process must abort. */
export function reportEnvironment(): boolean {
  const { fatal, warnings } = validateEnvironment();
  for (const w of warnings) console.warn(`[env] ${w.severity}: ${w.message}`);
  for (const f of fatal) console.error(`[env] ${f.severity}: ${f.message}`);
  return fatal.length === 0;
}
