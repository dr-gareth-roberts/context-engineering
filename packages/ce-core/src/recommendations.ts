/**
 * Closed-Loop Budget Tuning & A/B Scoring Weights
 *
 * Fetches budget recommendations and scoring weight configurations from
 * external HTTP endpoints, enabling:
 * 1. Closed-loop budget tuning — telemetry informs future budget decisions
 * 2. A/B testing of scoring weights — experiment with different packing strategies
 *
 * Design: never throws. Returns fallback values on any failure (network,
 * timeout, malformed response). Logs warnings via the Logger interface.
 */

import type { Logger } from "./logger.js";
import { noopLogger } from "./logger.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BudgetRecommendation {
  maxTokens: number;
  reserveTokens?: number;
  /** 0-1, how confident the recommendation is */
  confidence: number;
  /** "make.com" | "custom" | "default" */
  source: string;
  /** Human-readable reason for the recommendation */
  reason?: string;
}

export interface WeightConfig {
  /** Config identifier for A/B tracking */
  id: string;
  priority: number;
  recency: number;
  salience: number;
  metadata?: Record<string, unknown>;
}

export interface RecommendationOptions {
  /** URL to fetch budget recommendations from */
  budgetUrl?: string;
  /** URL to fetch weight configs from */
  weightsUrl?: string;
  /** Timeout in ms (default: 3000) */
  timeoutMs?: number;
  /** Headers to send with requests */
  headers?: Record<string, string>;
  /** Fallback budget if fetch fails */
  fallbackBudget?: number;
  /** Fallback weights if fetch fails */
  fallbackWeights?: { priority: number; recency: number; salience: number };
  /** Logger for warnings/debug (default: noopLogger) */
  logger?: Logger;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_TIMEOUT_MS = 3000;
const DEFAULT_BUDGET: BudgetRecommendation = {
  maxTokens: 128_000,
  confidence: 0,
  source: "default",
  reason: "No recommendation source configured",
};
const DEFAULT_WEIGHTS: WeightConfig = {
  id: "default",
  priority: 1.0,
  recency: 0.7,
  salience: 0.5,
};

// ---------------------------------------------------------------------------
// Environment helpers
// ---------------------------------------------------------------------------

/**
 * Create RecommendationOptions from environment variables.
 * Reads `CE_BUDGET_URL` and `CE_WEIGHTS_URL`.
 */
export function recommendationOptionsFromEnv(): RecommendationOptions {
  return {
    budgetUrl: process.env.CE_BUDGET_URL,
    weightsUrl: process.env.CE_WEIGHTS_URL,
  };
}

// ---------------------------------------------------------------------------
// Internal fetch helper
// ---------------------------------------------------------------------------

async function fetchJson(
  url: string,
  timeoutMs: number,
  headers: Record<string, string>,
  logger: Logger
): Promise<unknown | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json", ...headers },
      signal: controller.signal,
    });

    if (!response.ok) {
      logger.warn("Recommendation fetch returned non-OK status", {
        url,
        status: response.status,
      });
      return null;
    }

    return await response.json();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    logger.warn("Recommendation fetch failed", { url, error: message });
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Fetch a budget recommendation from an external source.
 *
 * Returns the recommendation, or a fallback if the fetch fails.
 * Never throws — always returns a usable value.
 *
 * @param sessionId - Session identifier sent as a query parameter
 * @param options - Configuration (URLs, timeout, fallbacks)
 *
 * @example
 * ```ts
 * const rec = await fetchBudgetRecommendation("session-123", {
 *   budgetUrl: "https://hook.make.com/budget",
 * });
 * const budget = { maxTokens: rec.maxTokens, reserveTokens: rec.reserveTokens };
 * ```
 */
export async function fetchBudgetRecommendation(
  sessionId: string,
  options?: RecommendationOptions
): Promise<BudgetRecommendation> {
  const env = recommendationOptionsFromEnv();
  const url = options?.budgetUrl ?? env.budgetUrl;
  const logger = options?.logger ?? noopLogger;
  const fallbackBudget = options?.fallbackBudget ?? DEFAULT_BUDGET.maxTokens;

  if (!url) {
    logger.debug("No budget URL configured, returning fallback");
    return {
      maxTokens: fallbackBudget,
      confidence: 0,
      source: "default",
      reason: "No recommendation source configured",
    };
  }

  const separator = url.includes("?") ? "&" : "?";
  const fullUrl = `${url}${separator}sessionId=${encodeURIComponent(sessionId)}`;

  const data = await fetchJson(
    fullUrl,
    options?.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    options?.headers ?? {},
    logger
  );

  if (data == null || typeof data !== "object") {
    return {
      maxTokens: fallbackBudget,
      confidence: 0,
      source: "default",
      reason: "Fetch failed or returned invalid data",
    };
  }

  const obj = data as Record<string, unknown>;
  const maxTokens =
    typeof obj.maxTokens === "number" && obj.maxTokens > 0
      ? obj.maxTokens
      : fallbackBudget;
  const reserveTokens =
    typeof obj.reserveTokens === "number" ? obj.reserveTokens : undefined;
  const confidence =
    typeof obj.confidence === "number"
      ? Math.max(0, Math.min(1, obj.confidence))
      : 0.5;
  const source = typeof obj.source === "string" ? obj.source : "custom";
  const reason = typeof obj.reason === "string" ? obj.reason : undefined;

  return { maxTokens, reserveTokens, confidence, source, reason };
}

/**
 * Fetch scoring weight config from an external source (for A/B testing).
 *
 * Returns a weight config with an ID for analytics tracking.
 * Never throws — always returns a usable value.
 *
 * @param sessionId - Session identifier sent as a query parameter
 * @param options - Configuration (URLs, timeout, fallbacks)
 *
 * @example
 * ```ts
 * const config = await fetchWeightConfig("session-123", {
 *   weightsUrl: "https://hook.make.com/weights",
 * });
 * const scorer = createScorer({
 *   priority: config.priority,
 *   recency: config.recency,
 *   salience: config.salience,
 * });
 * ```
 */
export async function fetchWeightConfig(
  sessionId: string,
  options?: RecommendationOptions
): Promise<WeightConfig> {
  const env = recommendationOptionsFromEnv();
  const url = options?.weightsUrl ?? env.weightsUrl;
  const logger = options?.logger ?? noopLogger;
  const fallback = options?.fallbackWeights ?? {
    priority: DEFAULT_WEIGHTS.priority,
    recency: DEFAULT_WEIGHTS.recency,
    salience: DEFAULT_WEIGHTS.salience,
  };

  if (!url) {
    logger.debug("No weights URL configured, returning fallback");
    return {
      id: "default",
      ...fallback,
    };
  }

  const separator = url.includes("?") ? "&" : "?";
  const fullUrl = `${url}${separator}sessionId=${encodeURIComponent(sessionId)}`;

  const data = await fetchJson(
    fullUrl,
    options?.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    options?.headers ?? {},
    logger
  );

  if (data == null || typeof data !== "object") {
    return { id: "default", ...fallback };
  }

  const obj = data as Record<string, unknown>;
  const id = typeof obj.id === "string" ? obj.id : "default";
  const priority =
    typeof obj.priority === "number" ? obj.priority : fallback.priority;
  const recency =
    typeof obj.recency === "number" ? obj.recency : fallback.recency;
  const salience =
    typeof obj.salience === "number" ? obj.salience : fallback.salience;
  const metadata =
    typeof obj.metadata === "object" && obj.metadata != null
      ? (obj.metadata as Record<string, unknown>)
      : undefined;

  return { id, priority, recency, salience, metadata };
}
