/**
 * Webhook Telemetry Integration
 *
 * Fire-and-forget webhook reporting for pack/trace/handoff/pipeline/quality/cost.
 * Designed for Make.com scenario ingestion but works with any HTTP endpoint.
 *
 * Usage:
 * ```ts
 * const reporter = createWebhookReporter({ analyticsUrl: "https://..." });
 * const result = pack(items, budget);
 * reporter.reportPack(result);
 * ```
 *
 * Or rely on env vars:
 * ```ts
 * // reads CE_WEBHOOK_URL, CE_WEBHOOK_HANDOFF_URL, CE_WEBHOOK_QUALITY_URL, CE_WEBHOOK_COST_URL
 * const reporter = createWebhookReporter();
 * ```
 */

import type { ContextPack, ContextTrace } from "./types.js";
import type { ContextQuality } from "./quality.js";
import type { CostEstimate } from "./cost.js";
import type { HandoffResult } from "./beads.js";
import type { PipelineResult } from "./pipeline.js";
import type { Logger } from "./logger.js";
import { noopLogger } from "./logger.js";

// ─── Types ───────────────────────────────────────────────────────────

export interface WebhookOptions {
  /** URL for analytics/telemetry webhook (pack/trace results) */
  analyticsUrl?: string;
  /** URL for handoff webhook (BEADS handoff notifications) */
  handoffUrl?: string;
  /** URL for quality regression webhook */
  qualityUrl?: string;
  /** URL for cost anomaly webhook */
  costUrl?: string;
  /** Session identifier for correlation */
  sessionId?: string;
  /** Model name for telemetry */
  model?: string;
  /** Packing strategy label */
  strategy?: string;
  /** Logger for warning on failures */
  logger?: Logger;
  /** Fetch timeout in milliseconds (default: 5000) */
  timeoutMs?: number;
  /** Additional headers to send with requests */
  headers?: Record<string, string>;
}

export interface WebhookAnalyticsPayload {
  event_type: "pack" | "trace";
  session_id: string;
  model: string;
  strategy: string;
  timestamp: string;
  budget_max_tokens: number;
  budget_reserve_tokens: number;
  total_tokens: number;
  selected_count: number;
  dropped_count: number;
  budget_utilization_pct: number;
  remaining_tokens: number;
  quality_overall?: number;
  quality_density?: number;
  quality_diversity?: number;
  cost_with_cache?: number;
  cost_without_cache?: number;
  cache_hit_ratio?: number;
  trace_decisions?: string;
}

export interface WebhookHandoffPayload {
  event_type: "handoff";
  session_id: string;
  timestamp: string;
  total_issues: number;
  active_items: number;
  deferred_items: number;
  source_agent?: string;
  target_url?: string;
  jsonl_size_bytes: number;
}

export interface WebhookPipelinePayload {
  event_type: "pipeline";
  session_id: string;
  timestamp: string;
  model: string;
  strategy: string;
  stages: string[];
  input_count: number;
  selected_count: number;
  dropped_count: number;
  total_tokens: number;
  budget_max_tokens: number;
  budget_reserve_tokens: number;
  budget_utilization_pct: number;
  quality_overall?: number;
  quality_density?: number;
  quality_diversity?: number;
  cache_efficiency?: number;
  cacheable_tokens?: number;
  cache_key?: string;
  allocation_efficiency?: number;
  allocations_json?: string;
  placement_strategy?: string;
}

export interface WebhookQualityPayload {
  event_type: "quality";
  session_id: string;
  timestamp: string;
  model: string;
  quality_overall: number;
  quality_density: number;
  quality_diversity: number;
  selected_count: number;
  dropped_count: number;
  budget_utilization_pct: number;
}

export interface WebhookCostPayload {
  event_type: "cost";
  session_id: string;
  timestamp: string;
  model: string;
  cost_with_cache: number;
  cost_without_cache: number;
  cache_hit_ratio: number;
  total_tokens: number;
  budget_max_tokens: number;
}

export interface PackReportExtras {
  quality?: ContextQuality;
  cost?: CostEstimate;
  cacheHitRatio?: number;
}

export interface HandoffReportExtras {
  sourceAgent?: string;
  targetUrl?: string;
}

export interface PipelineReportExtras {
  cost?: CostEstimate;
  cacheHitRatio?: number;
  placementStrategy?: string;
}

export interface WebhookReporter {
  reportPack(pack: ContextPack, extras?: PackReportExtras): void;
  reportTrace(trace: ContextTrace, extras?: PackReportExtras): void;
  reportHandoff(handoff: HandoffResult, extras?: HandoffReportExtras): void;
  reportPipeline(result: PipelineResult, extras?: PipelineReportExtras): void;
  reportQuality(pack: ContextPack, quality: ContextQuality): void;
  reportCost(
    pack: ContextPack,
    cost: CostEstimate,
    cacheHitRatio?: number
  ): void;
}

// ─── No-op Reporter ──────────────────────────────────────────────────

/** Explicit no-op reporter that never sends anything. */
export const noopReporter: WebhookReporter = {
  reportPack() {},
  reportTrace() {},
  reportHandoff() {},
  reportPipeline() {},
  reportQuality() {},
  reportCost() {},
};

// ─── Internal Helpers ────────────────────────────────────────────────

function computeUtilization(
  totalTokens: number,
  maxTokens: number,
  reserveTokens: number
): number {
  const effective = maxTokens - reserveTokens;
  return effective > 0
    ? Math.round((totalTokens / effective) * 10000) / 100
    : 0;
}

function fireWebhook(
  url: string,
  payload: unknown,
  logger: Logger,
  timeoutMs: number,
  headers?: Record<string, string>
): void {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then(() => {
      clearTimeout(timer);
    })
    .catch((err: unknown) => {
      clearTimeout(timer);
      const msg = err instanceof Error ? err.message : String(err);
      logger.warn("webhook:send_failed", { url, error: msg });
    });
}

function buildAnalyticsPayload(
  pack: ContextPack,
  eventType: "pack" | "trace",
  sessionId: string,
  model: string,
  strategy: string,
  extras?: PackReportExtras,
  traceDecisions?: string
): WebhookAnalyticsPayload {
  const maxTokens = pack.budget.maxTokens;
  const reserveTokens = pack.budget.reserveTokens ?? 0;
  const utilizationPct = computeUtilization(
    pack.totalTokens,
    maxTokens,
    reserveTokens
  );

  return {
    event_type: eventType,
    session_id: sessionId,
    model,
    strategy,
    timestamp: new Date().toISOString(),
    budget_max_tokens: maxTokens,
    budget_reserve_tokens: reserveTokens,
    total_tokens: pack.totalTokens,
    selected_count: pack.selected.length,
    dropped_count: pack.dropped.length,
    budget_utilization_pct: utilizationPct,
    remaining_tokens: Math.max(0, maxTokens - reserveTokens - pack.totalTokens),
    quality_overall: extras?.quality?.overall,
    quality_density: extras?.quality?.density,
    quality_diversity: extras?.quality?.diversity,
    cost_with_cache: extras?.cost?.costWithCache,
    cost_without_cache: extras?.cost?.costWithoutCache,
    cache_hit_ratio: extras?.cacheHitRatio,
    trace_decisions: traceDecisions,
  };
}

function buildPipelinePayload(
  result: PipelineResult,
  sessionId: string,
  model: string,
  strategy: string,
  extras?: PipelineReportExtras
): WebhookPipelinePayload {
  const maxTokens = result.budget.maxTokens;
  const reserveTokens = result.budget.reserveTokens ?? 0;

  const payload: WebhookPipelinePayload = {
    event_type: "pipeline",
    session_id: sessionId,
    timestamp: new Date().toISOString(),
    model,
    strategy,
    stages: result.stages,
    input_count: result.inputCount,
    selected_count: result.selected.length,
    dropped_count: result.dropped.length,
    total_tokens: result.totalTokens,
    budget_max_tokens: maxTokens,
    budget_reserve_tokens: reserveTokens,
    budget_utilization_pct: computeUtilization(
      result.totalTokens,
      maxTokens,
      reserveTokens
    ),
  };

  if (result.quality) {
    payload.quality_overall = result.quality.overall;
    payload.quality_density = result.quality.density;
    payload.quality_diversity = result.quality.diversity;
  }
  if (result.cacheEfficiency !== undefined) {
    payload.cache_efficiency = result.cacheEfficiency;
  }
  if (result.cacheableTokens !== undefined) {
    payload.cacheable_tokens = result.cacheableTokens;
  }
  if (result.cacheKey !== undefined) {
    payload.cache_key = result.cacheKey;
  }
  if (result.allocationEfficiency !== undefined) {
    payload.allocation_efficiency = result.allocationEfficiency;
  }
  if (result.allocations !== undefined) {
    payload.allocations_json = JSON.stringify(result.allocations);
  }
  if (extras?.placementStrategy) {
    payload.placement_strategy = extras.placementStrategy;
  }

  return payload;
}

// ─── Factory ─────────────────────────────────────────────────────────

/**
 * Create a webhook reporter for telemetry.
 *
 * Reads env vars as defaults:
 * - `CE_WEBHOOK_URL` — pack/trace analytics
 * - `CE_WEBHOOK_HANDOFF_URL` — handoff events
 * - `CE_WEBHOOK_QUALITY_URL` — quality regression reports
 * - `CE_WEBHOOK_COST_URL` — cost anomaly reports
 *
 * Returns no-op methods when no URL is configured.
 */
export function createWebhookReporter(
  options: WebhookOptions = {}
): WebhookReporter {
  const analyticsUrl = options.analyticsUrl ?? process.env.CE_WEBHOOK_URL ?? "";
  const handoffUrl =
    options.handoffUrl ?? process.env.CE_WEBHOOK_HANDOFF_URL ?? "";
  const qualityUrl =
    options.qualityUrl ?? process.env.CE_WEBHOOK_QUALITY_URL ?? "";
  const costUrl = options.costUrl ?? process.env.CE_WEBHOOK_COST_URL ?? "";
  const sessionId = options.sessionId ?? `ce-${Date.now().toString(36)}`;
  const model = options.model ?? "unknown";
  const strategy = options.strategy ?? "greedy-score";
  const logger = options.logger ?? noopLogger;
  const timeoutMs = options.timeoutMs ?? 5000;
  const headers = options.headers;

  if (!analyticsUrl && !handoffUrl && !qualityUrl && !costUrl) {
    return noopReporter;
  }

  return {
    reportPack(pack: ContextPack, extras?: PackReportExtras): void {
      if (!analyticsUrl) return;
      const payload = buildAnalyticsPayload(
        pack,
        "pack",
        sessionId,
        model,
        strategy,
        extras
      );
      fireWebhook(analyticsUrl, payload, logger, timeoutMs, headers);
    },

    reportTrace(trace: ContextTrace, extras?: PackReportExtras): void {
      if (!analyticsUrl) return;
      const traceDecisions = JSON.stringify(
        trace.steps.map(s => ({
          id: s.id,
          decision: s.decision,
          tokens: s.tokens,
          reason: s.reason,
        }))
      );
      const payload = buildAnalyticsPayload(
        trace.pack,
        "trace",
        sessionId,
        model,
        strategy,
        extras,
        traceDecisions
      );
      fireWebhook(analyticsUrl, payload, logger, timeoutMs, headers);
    },

    reportHandoff(handoff: HandoffResult, extras?: HandoffReportExtras): void {
      if (!handoffUrl) return;
      const payload: WebhookHandoffPayload = {
        event_type: "handoff",
        session_id: sessionId,
        timestamp: new Date().toISOString(),
        total_issues: handoff.stats.totalIssues,
        active_items: handoff.stats.activeItems,
        deferred_items: handoff.stats.deferredItems,
        source_agent: extras?.sourceAgent,
        target_url: extras?.targetUrl,
        jsonl_size_bytes: new TextEncoder().encode(handoff.jsonl).byteLength,
      };
      fireWebhook(handoffUrl, payload, logger, timeoutMs, headers);
    },

    reportPipeline(
      result: PipelineResult,
      extras?: PipelineReportExtras
    ): void {
      if (!analyticsUrl) return;
      const payload = buildPipelinePayload(
        result,
        sessionId,
        model,
        strategy,
        extras
      );
      fireWebhook(analyticsUrl, payload, logger, timeoutMs, headers);
    },

    reportQuality(pack: ContextPack, quality: ContextQuality): void {
      if (!qualityUrl) return;
      const maxTokens = pack.budget.maxTokens;
      const reserveTokens = pack.budget.reserveTokens ?? 0;
      const payload: WebhookQualityPayload = {
        event_type: "quality",
        session_id: sessionId,
        timestamp: new Date().toISOString(),
        model,
        quality_overall: quality.overall,
        quality_density: quality.density,
        quality_diversity: quality.diversity,
        selected_count: pack.selected.length,
        dropped_count: pack.dropped.length,
        budget_utilization_pct: computeUtilization(
          pack.totalTokens,
          maxTokens,
          reserveTokens
        ),
      };
      fireWebhook(qualityUrl, payload, logger, timeoutMs, headers);
    },

    reportCost(
      pack: ContextPack,
      cost: CostEstimate,
      cacheHitRatio?: number
    ): void {
      if (!costUrl) return;
      const payload: WebhookCostPayload = {
        event_type: "cost",
        session_id: sessionId,
        timestamp: new Date().toISOString(),
        model,
        cost_with_cache: cost.costWithCache,
        cost_without_cache: cost.costWithoutCache,
        cache_hit_ratio: cacheHitRatio ?? cost.cacheEfficiency,
        total_tokens: cost.inputTokens,
        budget_max_tokens: pack.budget.maxTokens,
      };
      fireWebhook(costUrl, payload, logger, timeoutMs, headers);
    },
  };
}
