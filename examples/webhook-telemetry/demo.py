#!/usr/bin/env python3
"""
Webhook Telemetry Demo — Context Engineering Toolkit (Python)

Demonstrates the full telemetry pipeline:
1. Pack context items with budget constraints
2. Analyze quality metrics
3. Estimate costs with cache savings
4. Fire webhook telemetry to Make.com (or any HTTP endpoint)
5. Fetch closed-loop budget recommendations
6. A/B test scoring weights

Run with:
  CE_WEBHOOK_URL=https://hook.us1.make.com/your-url python demo.py

Or without webhooks to see the payloads locally:
  python demo.py
"""

from __future__ import annotations

import json
import os
import sys
import time

# Add the parent package to the path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python"))

from context_engineering import (
    Budget,
    ContextItem,
    ScoringWeights,
    analyze_context,
    create_handoff,
    create_webhook_reporter,
    estimate_cost,
    pack,
    pack_with_cache_topology,
    trace_pack,
    create_pipeline,
)
from context_engineering.beads import HandoffOptions
from context_engineering.recommendations import (
    RecommendationOptions,
    fetch_budget_recommendation,
    fetch_weight_config,
)

# ─── ANSI Colors ──────────────────────────────────────────────────────


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def header(text: str) -> None:
    line = "─" * 60
    print(f"\n{C.CYAN}{line}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {text}{C.RESET}")
    print(f"{C.CYAN}{line}{C.RESET}\n")


def kv(key: str, value: str, color: str = C.CYAN) -> None:
    print(f"  {C.DIM}{key:<22}{C.RESET}{color}{value}{C.RESET}")


def bar(label: str, value: float, maximum: float, width: int = 30) -> None:
    pct = min(1.0, value / maximum) if maximum > 0 else 0
    filled = round(pct * width)
    empty = width - filled
    color = C.RED if pct > 0.8 else C.YELLOW if pct > 0.5 else C.GREEN
    bar_str = f"{color}{'█' * filled}{C.DIM}{'░' * empty}{C.RESET}"
    print(f"  {label:<22}{bar_str} {color}{pct * 100:.1f}%{C.RESET}")


def show_json(label: str, obj: dict) -> None:
    print(f"  {C.DIM}{label}:{C.RESET}")
    for line in json.dumps(obj, indent=2).split("\n"):
        print(f"    {C.DIM}{line}{C.RESET}")


# ─── Sample Context Items ────────────────────────────────────────────

items = [
    ContextItem(
        id="system-prompt",
        content="You are a senior software engineer. Follow SOLID principles. Write clean, tested code.",
        kind="system",
        priority=1.0,
        recency=0.5,
        tokens=25,
    ),
    ContextItem(
        id="arch-decision",
        content="ADR-042: Migrate from REST to GraphQL for the public API.",
        kind="knowledge",
        priority=0.9,
        recency=0.8,
        salience=0.95,
        tokens=35,
    ),
    ContextItem(
        id="perf-requirement",
        content="P99 latency must stay under 200ms for all API endpoints. Current P99: 180ms.",
        kind="constraint",
        priority=0.85,
        recency=0.3,
        tokens=22,
    ),
    ContextItem(
        id="recent-pr",
        content="PR #847: Refactored auth middleware to use JWT validation with RS256.",
        kind="code-change",
        priority=0.7,
        recency=1.0,
        salience=0.8,
        tokens=30,
    ),
    ContextItem(
        id="debug-context",
        content='User reported 500 error on /api/users. Root cause: missing null check on "avatar_url".',
        kind="debug",
        priority=0.95,
        recency=1.0,
        salience=1.0,
        tokens=45,
    ),
    ContextItem(
        id="team-convention",
        content="Team conventions: use pnpm, Vitest for testing, Prettier with double quotes.",
        kind="convention",
        priority=0.6,
        recency=0.2,
        tokens=28,
    ),
    ContextItem(
        id="stale-meeting-notes",
        content="Sprint retro from 3 months ago: discussed moving to Kubernetes.",
        kind="notes",
        priority=0.2,
        recency=0.1,
        tokens=22,
    ),
    ContextItem(
        id="api-docs",
        content="OpenAPI spec v3.1 for /api/users: GET returns UserProfile{ id, name, email }.",
        kind="documentation",
        priority=0.75,
        recency=0.6,
        salience=0.7,
        tokens=40,
    ),
    ContextItem(
        id="low-value-log",
        content="Build log from CI: 847 tests passed, 0 failed. Duration: 2m 34s.",
        kind="log",
        priority=0.1,
        recency=0.9,
        tokens=18,
    ),
    ContextItem(
        id="security-alert",
        content="CVE-2026-1234: Critical XSS vulnerability in template engine v4.2.0.",
        kind="alert",
        priority=1.0,
        recency=1.0,
        salience=1.0,
        tokens=35,
    ),
]

# ─── 1. Pack with Telemetry ──────────────────────────────────────────

header("1. Context Pack + Webhook Telemetry")

budget_tokens = 200
budget = Budget(maxTokens=budget_tokens)
result = pack(items, budget)

kv("Budget", f"{budget_tokens} tokens")
kv("Selected", f"{len(result.selected)} items", C.GREEN)
kv("Dropped", f"{len(result.dropped)} items", C.RED)
kv("Total tokens", str(result.total_tokens))
bar("Budget utilization", result.total_tokens, budget_tokens)

print(f"\n  {C.BOLD}Selected items:{C.RESET}")
for item in result.selected:
    icon = (
        f"{C.RED}!"
        if (item.priority or 0) >= 0.9
        else f"{C.YELLOW}*"
        if (item.priority or 0) >= 0.7
        else f"{C.GREEN}·"
    )
    print(
        f"    {icon}{C.RESET} {C.BOLD}{item.id}{C.RESET} {C.DIM}({item.tokens}t, p={item.priority}){C.RESET}"
    )

print(f"\n  {C.BOLD}Dropped items:{C.RESET}")
for item in result.dropped:
    print(f"    {C.DIM}✗ {item.id} ({item.tokens}t, p={item.priority}){C.RESET}")

# ─── 2. Quality Analysis ─────────────────────────────────────────────

header("2. Context Quality Analysis")

quality = analyze_context(result.selected)

color = C.GREEN if quality.overall > 0.7 else C.YELLOW
kv("Overall score", f"{quality.overall:.3f}", color)
bar("Density", quality.density, 1)
bar("Diversity", quality.diversity, 1)
bar("Freshness", quality.freshness, 1)
bar("Redundancy", quality.redundancy, 1)
kv("Item count", str(quality.item_count))
kv("Total tokens", str(quality.total_tokens))

# ─── 3. Cost Estimation ──────────────────────────────────────────────

header("3. Cost Estimation with Cache Savings")

model = "claude-sonnet-4-6"
cache_pack = pack_with_cache_topology(items, budget)
cost = estimate_cost(cache_pack, model, output_tokens=500)

kv("Model", model)
kv("Input tokens", str(cost.input_tokens))
kv("Cached tokens", str(cost.cached_tokens), C.GREEN)
kv("Uncached tokens", str(cost.uncached_tokens))
kv("Without cache", f"${cost.cost_without_cache:.6f}")
kv("With cache", f"${cost.cost_with_cache:.6f}", C.GREEN)
kv("Savings", f"${cost.savings:.6f} ({cost.savings_percent}%)", C.GREEN)
bar("Cache efficiency", cost.cache_efficiency, 1)

# ─── 4. Trace Decisions ──────────────────────────────────────────────

header("4. Pack Trace — Decision Log")

trace = trace_pack(items, budget)

for step in trace.steps:
    if step.decision == "include":
        icon = f"{C.GREEN}✓"
    elif step.decision == "compress":
        icon = f"{C.YELLOW}~"
    else:
        icon = f"{C.RED}✗"
    tokens_str = f"{step.tokens}t".ljust(5)
    print(
        f"  {icon}{C.RESET} {tokens_str} {C.BOLD}{step.id:<20}{C.RESET} {C.DIM}{step.reason}{C.RESET}"
    )

# ─── 5. Pipeline ─────────────────────────────────────────────────────

header("5. Full Pipeline with Telemetry")

pipeline_result = (
    create_pipeline(budget).add_many(items).cache_topology().quality_gate(0.5).build()
)

kv("Stages", " → ".join(pipeline_result.stages))
kv("Input count", str(pipeline_result.input_count))
kv("Selected", f"{len(pipeline_result.selected)} items", C.GREEN)
kv("Dropped", f"{len(pipeline_result.dropped)} items", C.RED)
kv("Total tokens", str(pipeline_result.total_tokens))
if pipeline_result.quality:
    kv("Quality score", f"{pipeline_result.quality.overall:.3f}")
if pipeline_result.cache_efficiency is not None:
    bar("Cache efficiency", pipeline_result.cache_efficiency, 1)

# ─── 6. Webhook Reporting ────────────────────────────────────────────

header("6. Webhook Telemetry Payloads")

webhook_url = os.environ.get("CE_WEBHOOK_URL")
handoff_url = os.environ.get("CE_WEBHOOK_HANDOFF_URL")
quality_url = os.environ.get("CE_WEBHOOK_QUALITY_URL")
cost_url = os.environ.get("CE_WEBHOOK_COST_URL")

if any([webhook_url, handoff_url, quality_url, cost_url]):
    print(f"  {C.GREEN}Live webhooks detected — firing telemetry!{C.RESET}\n")
    if webhook_url:
        kv("Analytics URL", webhook_url)
    if handoff_url:
        kv("Handoff URL", handoff_url)
    if quality_url:
        kv("Quality URL", quality_url)
    if cost_url:
        kv("Cost URL", cost_url)

    reporter = create_webhook_reporter(
        session_id=f"demo-{int(time.time()):x}",
        model=model,
        strategy="greedy-score",
    )

    from context_engineering.webhook import PackReportExtras

    reporter.report_pack(
        result,
        PackReportExtras(
            quality=quality, cost=cost, cache_hit_ratio=cost.cache_efficiency
        ),
    )
    reporter.report_trace(trace)
    reporter.report_pipeline(pipeline_result)
    reporter.report_quality(result, quality)
    reporter.report_cost(result, cost, cache_hit_ratio=cost.cache_efficiency)

    print(f"\n  {C.GREEN}{C.BOLD}5 webhook events fired!{C.RESET}")
else:
    print(
        f"  {C.YELLOW}No webhook URLs configured — showing payload previews{C.RESET}\n"
    )

    session_id = f"demo-{int(time.time()):x}"

    show_json(
        "Pack Analytics Payload",
        {
            "event_type": "pack",
            "session_id": session_id,
            "model": model,
            "strategy": "greedy-score",
            "budget_max_tokens": budget_tokens,
            "total_tokens": result.total_tokens,
            "selected_count": len(result.selected),
            "dropped_count": len(result.dropped),
            "budget_utilization_pct": round(result.total_tokens / budget_tokens * 10000)
            / 100,
            "quality_overall": quality.overall,
            "cost_with_cache": cost.cost_with_cache,
            "cost_without_cache": cost.cost_without_cache,
        },
    )

    show_json(
        "Quality Payload",
        {
            "event_type": "quality",
            "session_id": session_id,
            "quality_overall": quality.overall,
            "quality_density": quality.density,
            "quality_diversity": quality.diversity,
        },
    )

    show_json(
        "Cost Payload",
        {
            "event_type": "cost",
            "session_id": session_id,
            "cost_with_cache": cost.cost_with_cache,
            "cost_without_cache": cost.cost_without_cache,
            "cache_hit_ratio": cost.cache_efficiency,
        },
    )

    print(
        f"\n  {C.DIM}Set CE_WEBHOOK_URL to fire these to Make.com or any HTTP endpoint{C.RESET}"
    )

# ─── 7. BEADS Handoff ────────────────────────────────────────────────

header("7. BEADS Agent Handoff")

handoff = create_handoff(
    result,
    HandoffOptions(
        agent="demo-agent",
        session_id="demo-session",
        handoff_notes="Debugging avatar_url null pointer in UserService",
        include_dropped=True,
    ),
)

kv("Total issues", str(handoff.stats["totalIssues"]))
kv("Active items", str(handoff.stats["activeItems"]), C.GREEN)
kv("Deferred items", str(handoff.stats["deferredItems"]), C.YELLOW)
kv("JSONL size", f"{len(handoff.jsonl.encode('utf-8'))} bytes")

print(f"\n  {C.BOLD}JSONL preview (first 3 lines):{C.RESET}")
for line in handoff.jsonl.split("\n")[:3]:
    if line.strip():
        print(f"    {C.DIM}{line[:80]}...{C.RESET}")

# ─── 8. Closed-Loop Budget Recommendation ────────────────────────────

header("8. Closed-Loop Budget Recommendation")

budget_rec = fetch_budget_recommendation(
    "demo-session",
    RecommendationOptions(fallback_budget=budget_tokens),
)

kv("Recommended budget", f"{budget_rec.max_tokens} tokens")
kv("Confidence", f"{budget_rec.confidence * 100:.0f}%")
kv("Source", budget_rec.source)
if budget_rec.reason:
    kv("Reason", budget_rec.reason)

if budget_rec.source == "default":
    print(
        f"\n  {C.DIM}Set CE_BUDGET_URL to receive live recommendations from Make.com{C.RESET}"
    )

# ─── 9. A/B Scoring Weights ──────────────────────────────────────────

header("9. A/B Scoring Weight Experiment")

weights = fetch_weight_config(
    "demo-session",
    RecommendationOptions(
        fallback_weights={"priority": 1.0, "recency": 0.7, "salience": 0.5},
    ),
)

kv("Config ID", weights.id)
kv("Priority weight", str(weights.priority))
kv("Recency weight", str(weights.recency))
kv("Salience weight", str(weights.salience))

# Show how different weights affect packing
custom_weights = ScoringWeights(
    priority=weights.priority,
    recency=weights.recency,
    salience=weights.salience,
)

default_result = pack(items, budget)
custom_result = pack(items, budget, weights=custom_weights)

print(f"\n  {C.BOLD}Default weights vs A/B config:{C.RESET}")
kv("Default selected", f"{len(default_result.selected)} items")
kv("A/B selected", f"{len(custom_result.selected)} items")
kv("Default tokens", str(default_result.total_tokens))
kv("A/B tokens", str(custom_result.total_tokens))

if weights.id == "default":
    print(
        f"\n  {C.DIM}Set CE_WEIGHTS_URL to receive live A/B configs from Make.com{C.RESET}"
    )

# ─── Summary ─────────────────────────────────────────────────────────

header("Summary")

print(f"  {C.BOLD}{C.GREEN}Context Engineering Telemetry Demo Complete{C.RESET}\n")
print(f"  {C.BOLD}Features demonstrated:{C.RESET}")
features = [
    "Pack with budget constraints",
    "Quality analysis (density, diversity, freshness, redundancy)",
    "Cost estimation with prefix cache savings",
    "Decision trace logging",
    "Full pipeline (pack → cache topology → quality gate)",
    "Webhook telemetry (pack, trace, pipeline, quality, cost)",
    "BEADS agent handoff",
    "Closed-loop budget recommendations",
    "A/B scoring weight experimentation",
]
for i, feature in enumerate(features, 1):
    print(f"    {C.CYAN}{i}.{C.RESET} {feature}")

print(f"\n  {C.BOLD}Environment variables:{C.RESET}")
env_vars = [
    ("CE_WEBHOOK_URL", "Pack/trace/pipeline analytics"),
    ("CE_WEBHOOK_HANDOFF_URL", "Handoff notifications"),
    ("CE_WEBHOOK_QUALITY_URL", "Quality regression alerts"),
    ("CE_WEBHOOK_COST_URL", "Cost anomaly alerts"),
    ("CE_BUDGET_URL", "Closed-loop budget tuning"),
    ("CE_WEIGHTS_URL", "A/B scoring weight configs"),
]
for var, desc in env_vars:
    print(f"    {C.DIM}{var:<26}{C.RESET}→ {desc}")
print()
