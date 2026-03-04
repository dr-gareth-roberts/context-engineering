#!/usr/bin/env node
/**
 * Webhook Telemetry Demo — Context Engineering Toolkit
 *
 * Demonstrates the full telemetry pipeline:
 * 1. Pack context items with budget constraints
 * 2. Analyze quality metrics
 * 3. Estimate costs with cache savings
 * 4. Fire webhook telemetry to Make.com (or any HTTP endpoint)
 * 5. Fetch closed-loop budget recommendations
 * 6. A/B test scoring weights
 *
 * Run with:
 *   CE_WEBHOOK_URL=https://hook.us1.make.com/your-url node demo.mjs
 *
 * Or without webhooks to see the payloads locally:
 *   node demo.mjs
 */

import {
  pack,
  tracePack,
  analyzeContext,
  createScorer,
  estimateCost,
  packWithCacheTopology,
  createHandoff,
  createWebhookReporter,
  fetchBudgetRecommendation,
  fetchWeightConfig,
  pipeline,
} from "@context-engineering/core";

// ─── Sample Context Items ────────────────────────────────────────────

const items = [
  {
    id: "system-prompt",
    content:
      "You are a senior software engineer. Follow SOLID principles. Write clean, tested code.",
    kind: "system",
    priority: 1.0,
    recency: 0.5,
    tokens: 25,
  },
  {
    id: "arch-decision",
    content:
      "ADR-042: Migrate from REST to GraphQL for the public API. Rationale: reduced over-fetching, type safety, better DX.",
    kind: "knowledge",
    priority: 0.9,
    recency: 0.8,
    salience: 0.95,
    tokens: 35,
  },
  {
    id: "perf-requirement",
    content:
      "P99 latency must stay under 200ms for all API endpoints. Current P99: 180ms.",
    kind: "constraint",
    priority: 0.85,
    recency: 0.3,
    tokens: 22,
  },
  {
    id: "recent-pr",
    content:
      "PR #847: Refactored auth middleware to use JWT validation with RS256. Added rate limiting (100 req/min per user).",
    kind: "code-change",
    priority: 0.7,
    recency: 1.0,
    salience: 0.8,
    tokens: 30,
  },
  {
    id: "debug-context",
    content:
      'User reported 500 error on /api/users endpoint. Stack trace points to null pointer in UserService.getProfile(). Root cause: missing null check on optional field "avatar_url".',
    kind: "debug",
    priority: 0.95,
    recency: 1.0,
    salience: 1.0,
    tokens: 45,
  },
  {
    id: "team-convention",
    content:
      "Team conventions: use pnpm, Vitest for testing, Prettier with double quotes, 2-space indent. All PRs require 2 approvals.",
    kind: "convention",
    priority: 0.6,
    recency: 0.2,
    tokens: 28,
  },
  {
    id: "stale-meeting-notes",
    content:
      "Sprint retro from 3 months ago: discussed moving to Kubernetes. Decision deferred to Q3.",
    kind: "notes",
    priority: 0.2,
    recency: 0.1,
    tokens: 22,
  },
  {
    id: "api-docs",
    content:
      "OpenAPI spec v3.1 for /api/users: GET returns UserProfile{ id, name, email, avatar_url?, role }. POST creates user. PATCH updates fields. DELETE soft-deletes.",
    kind: "documentation",
    priority: 0.75,
    recency: 0.6,
    salience: 0.7,
    tokens: 40,
  },
  {
    id: "low-value-log",
    content: "Build log from CI: 847 tests passed, 0 failed. Duration: 2m 34s.",
    kind: "log",
    priority: 0.1,
    recency: 0.9,
    tokens: 18,
  },
  {
    id: "security-alert",
    content:
      "CVE-2026-1234: Critical XSS vulnerability in template engine v4.2.0. Upgrade to v4.2.1 immediately. Affects all user-facing pages.",
    kind: "alert",
    priority: 1.0,
    recency: 1.0,
    salience: 1.0,
    tokens: 35,
  },
];

// ─── Pretty Printing ─────────────────────────────────────────────────

const C = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  magenta: "\x1b[35m",
  cyan: "\x1b[36m",
  bg: {
    black: "\x1b[40m",
    blue: "\x1b[44m",
    magenta: "\x1b[45m",
  },
};

function header(text) {
  const line = "─".repeat(60);
  console.log(`\n${C.cyan}${line}${C.reset}`);
  console.log(`${C.bold}${C.cyan}  ${text}${C.reset}`);
  console.log(`${C.cyan}${line}${C.reset}\n`);
}

function kv(key, value, color = C.cyan) {
  console.log(`  ${C.dim}${key.padEnd(22)}${C.reset}${color}${value}${C.reset}`);
}

function bar(label, value, max, width = 30) {
  const pct = Math.min(1, value / max);
  const filled = Math.round(pct * width);
  const empty = width - filled;
  const color = pct > 0.8 ? C.red : pct > 0.5 ? C.yellow : C.green;
  const barStr = `${color}${"█".repeat(filled)}${C.dim}${"░".repeat(empty)}${C.reset}`;
  console.log(`  ${label.padEnd(22)}${barStr} ${color}${(pct * 100).toFixed(1)}%${C.reset}`);
}

function json(label, obj) {
  console.log(`  ${C.dim}${label}:${C.reset}`);
  const lines = JSON.stringify(obj, null, 2).split("\n");
  lines.forEach((line) => console.log(`    ${C.dim}${line}${C.reset}`));
}

// ─── 1. Pack with Telemetry ──────────────────────────────────────────

header("1. Context Pack + Webhook Telemetry");

const budget = 200;
const result = pack(items, { maxTokens: budget });

kv("Budget", `${budget} tokens`);
kv("Selected", `${result.selected.length} items`, C.green);
kv("Dropped", `${result.dropped.length} items`, C.red);
kv("Total tokens", `${result.totalTokens}`);
bar("Budget utilization", result.totalTokens, budget);

console.log(`\n  ${C.bold}Selected items:${C.reset}`);
result.selected.forEach((item) => {
  const icon =
    item.priority >= 0.9 ? `${C.red}!` : item.priority >= 0.7 ? `${C.yellow}*` : `${C.green}·`;
  console.log(
    `    ${icon}${C.reset} ${C.bold}${item.id}${C.reset} ${C.dim}(${item.tokens}t, p=${item.priority})${C.reset}`
  );
});

console.log(`\n  ${C.bold}Dropped items:${C.reset}`);
result.dropped.forEach((item) => {
  console.log(
    `    ${C.dim}✗ ${item.id} (${item.tokens}t, p=${item.priority})${C.reset}`
  );
});

// ─── 2. Quality Analysis ─────────────────────────────────────────────

header("2. Context Quality Analysis");

const quality = analyzeContext(result.selected);

kv("Overall score", quality.overall.toFixed(3), quality.overall > 0.7 ? C.green : C.yellow);
bar("Density", quality.density, 1);
bar("Diversity", quality.diversity, 1);
bar("Freshness", quality.freshness, 1);
bar("Redundancy", quality.redundancy, 1);
kv("Item count", String(quality.itemCount));
kv("Total tokens", String(quality.totalTokens));

// ─── 3. Cost Estimation ──────────────────────────────────────────────

header("3. Cost Estimation with Cache Savings");

const model = "claude-sonnet-4-6";
const cachePack = packWithCacheTopology(items, { maxTokens: budget });
const cost = estimateCost(cachePack, model, 500);

kv("Model", model);
kv("Input tokens", String(cost.inputTokens));
kv("Cached tokens", `${cost.cachedTokens}`, C.green);
kv("Uncached tokens", String(cost.uncachedTokens));
kv("Without cache", `$${cost.costWithoutCache.toFixed(6)}`);
kv("With cache", `$${cost.costWithCache.toFixed(6)}`, C.green);
kv("Savings", `$${cost.savings.toFixed(6)} (${cost.savingsPercent}%)`, C.green);
bar("Cache efficiency", cost.cacheEfficiency, 1);

// ─── 4. Trace Decisions ──────────────────────────────────────────────

header("4. Pack Trace — Decision Log");

const trace = tracePack(items, { maxTokens: budget });

trace.steps.forEach((step) => {
  const icon =
    step.decision === "include"
      ? `${C.green}✓`
      : step.decision === "compress"
        ? `${C.yellow}~`
        : `${C.red}✗`;
  const tokens = `${step.tokens}t`.padEnd(5);
  console.log(
    `  ${icon}${C.reset} ${tokens} ${C.bold}${step.id.padEnd(20)}${C.reset} ${C.dim}${step.reason}${C.reset}`
  );
});

// ─── 5. Pipeline (Fluent Builder) ────────────────────────────────────

header("5. Full Pipeline with Telemetry");

const pipelineResult = pipeline({ maxTokens: budget })
  .addMany(items)
  .cacheTopology()
  .qualityGate(0.5)
  .build();

kv("Stages", pipelineResult.stages.join(" → "));
kv("Input count", String(pipelineResult.inputCount));
kv("Selected", `${pipelineResult.selected.length} items`, C.green);
kv("Dropped", `${pipelineResult.dropped.length} items`, C.red);
kv("Total tokens", String(pipelineResult.totalTokens));
if (pipelineResult.quality) {
  kv("Quality score", pipelineResult.quality.overall.toFixed(3));
}
if (pipelineResult.cacheEfficiency !== undefined) {
  bar("Cache efficiency", pipelineResult.cacheEfficiency, 1);
}

// ─── 6. Webhook Reporting ────────────────────────────────────────────

header("6. Webhook Telemetry Payloads");

const webhookUrl = process.env.CE_WEBHOOK_URL;
const handoffUrl = process.env.CE_WEBHOOK_HANDOFF_URL;
const qualityUrl = process.env.CE_WEBHOOK_QUALITY_URL;
const costUrl = process.env.CE_WEBHOOK_COST_URL;

if (webhookUrl || handoffUrl || qualityUrl || costUrl) {
  console.log(`  ${C.green}Live webhooks detected — firing telemetry!${C.reset}\n`);
  if (webhookUrl) kv("Analytics URL", webhookUrl);
  if (handoffUrl) kv("Handoff URL", handoffUrl);
  if (qualityUrl) kv("Quality URL", qualityUrl);
  if (costUrl) kv("Cost URL", costUrl);

  const reporter = createWebhookReporter({
    sessionId: `demo-${Date.now().toString(36)}`,
    model,
    strategy: "greedy-score",
  });

  reporter.reportPack(result, {
    quality,
    cost,
    cacheHitRatio: cost.cacheEfficiency,
  });
  reporter.reportTrace(trace);
  reporter.reportPipeline(pipelineResult);
  reporter.reportQuality(result, quality);
  reporter.reportCost(result, cost, cost.cacheEfficiency);

  console.log(`\n  ${C.green}${C.bold}5 webhook events fired!${C.reset}`);
} else {
  console.log(`  ${C.yellow}No webhook URLs configured — showing payload previews${C.reset}\n`);

  // Show what the payloads would look like
  const sessionId = `demo-${Date.now().toString(36)}`;

  json("Pack Analytics Payload", {
    event_type: "pack",
    session_id: sessionId,
    model,
    strategy: "greedy-score",
    budget_max_tokens: budget,
    total_tokens: result.totalTokens,
    selected_count: result.selected.length,
    dropped_count: result.dropped.length,
    budget_utilization_pct:
      Math.round((result.totalTokens / budget) * 10000) / 100,
    quality_overall: quality.overall,
    cost_with_cache: cost.costWithCache,
    cost_without_cache: cost.costWithoutCache,
  });

  json("Quality Payload", {
    event_type: "quality",
    session_id: sessionId,
    quality_overall: quality.overall,
    quality_density: quality.density,
    quality_diversity: quality.diversity,
  });

  json("Cost Payload", {
    event_type: "cost",
    session_id: sessionId,
    cost_with_cache: cost.costWithCache,
    cost_without_cache: cost.costWithoutCache,
    cache_hit_ratio: cost.cacheEfficiency,
  });

  console.log(
    `\n  ${C.dim}Set CE_WEBHOOK_URL to fire these to Make.com or any HTTP endpoint${C.reset}`
  );
}

// ─── 7. BEADS Handoff ────────────────────────────────────────────────

header("7. BEADS Agent Handoff");

const handoff = createHandoff(result, {
  agent: "demo-agent",
  sessionId: "demo-session",
  handoffNotes: "Debugging avatar_url null pointer in UserService",
  includeDropped: true,
});

kv("Total issues", String(handoff.stats.totalIssues));
kv("Active items", String(handoff.stats.activeItems), C.green);
kv("Deferred items", String(handoff.stats.deferredItems), C.yellow);
kv("JSONL size", `${new TextEncoder().encode(handoff.jsonl).byteLength} bytes`);

console.log(`\n  ${C.bold}JSONL preview (first 3 lines):${C.reset}`);
handoff.jsonl
  .split("\n")
  .slice(0, 3)
  .forEach((line) => {
    const obj = JSON.parse(line);
    console.log(
      `    ${C.dim}${JSON.stringify(obj).slice(0, 80)}${obj ? "..." : ""}${C.reset}`
    );
  });

// ─── 8. Closed-Loop Budget Recommendation ────────────────────────────

header("8. Closed-Loop Budget Recommendation");

const budgetRec = await fetchBudgetRecommendation("demo-session", {
  fallbackBudget: budget,
});

kv("Recommended budget", `${budgetRec.maxTokens} tokens`);
kv("Confidence", `${(budgetRec.confidence * 100).toFixed(0)}%`);
kv("Source", budgetRec.source);
if (budgetRec.reason) kv("Reason", budgetRec.reason);

if (budgetRec.source === "default") {
  console.log(
    `\n  ${C.dim}Set CE_BUDGET_URL to receive live recommendations from Make.com${C.reset}`
  );
}

// ─── 9. A/B Scoring Weights ──────────────────────────────────────────

header("9. A/B Scoring Weight Experiment");

const weights = await fetchWeightConfig("demo-session", {
  fallbackWeights: { priority: 1.0, recency: 0.7, salience: 0.5 },
});

kv("Config ID", weights.id);
kv("Priority weight", String(weights.priority));
kv("Recency weight", String(weights.recency));
kv("Salience weight", String(weights.salience));

// Show how different weights affect packing
const customScorer = createScorer({
  priority: weights.priority,
  recency: weights.recency,
  salience: weights.salience,
});

const defaultResult = pack(items, { maxTokens: budget });
const customResult = pack(items, { maxTokens: budget }, { scorer: customScorer });

console.log(`\n  ${C.bold}Default weights vs A/B config:${C.reset}`);
kv("Default selected", `${defaultResult.selected.length} items`);
kv("A/B selected", `${customResult.selected.length} items`);
kv("Default tokens", String(defaultResult.totalTokens));
kv("A/B tokens", String(customResult.totalTokens));

if (weights.id === "default") {
  console.log(
    `\n  ${C.dim}Set CE_WEIGHTS_URL to receive live A/B configs from Make.com${C.reset}`
  );
}

// ─── Summary ─────────────────────────────────────────────────────────

header("Summary");

console.log(`  ${C.bold}${C.green}Context Engineering Telemetry Demo Complete${C.reset}\n`);
console.log(`  ${C.bold}Features demonstrated:${C.reset}`);
console.log(`    ${C.cyan}1.${C.reset} Pack with budget constraints`);
console.log(`    ${C.cyan}2.${C.reset} Quality analysis (density, diversity, freshness, redundancy)`);
console.log(`    ${C.cyan}3.${C.reset} Cost estimation with prefix cache savings`);
console.log(`    ${C.cyan}4.${C.reset} Decision trace logging`);
console.log(`    ${C.cyan}5.${C.reset} Full pipeline (pack → cache topology → quality gate)`);
console.log(`    ${C.cyan}6.${C.reset} Webhook telemetry (pack, trace, pipeline, quality, cost)`);
console.log(`    ${C.cyan}7.${C.reset} BEADS agent handoff`);
console.log(`    ${C.cyan}8.${C.reset} Closed-loop budget recommendations`);
console.log(`    ${C.cyan}9.${C.reset} A/B scoring weight experimentation`);

console.log(`\n  ${C.bold}Environment variables:${C.reset}`);
console.log(
  `    ${C.dim}CE_WEBHOOK_URL${C.reset}         → Pack/trace/pipeline analytics`
);
console.log(
  `    ${C.dim}CE_WEBHOOK_HANDOFF_URL${C.reset} → Handoff notifications`
);
console.log(
  `    ${C.dim}CE_WEBHOOK_QUALITY_URL${C.reset} → Quality regression alerts`
);
console.log(
  `    ${C.dim}CE_WEBHOOK_COST_URL${C.reset}    → Cost anomaly alerts`
);
console.log(
  `    ${C.dim}CE_BUDGET_URL${C.reset}          → Closed-loop budget tuning`
);
console.log(
  `    ${C.dim}CE_WEIGHTS_URL${C.reset}         → A/B scoring weight configs`
);
console.log();
