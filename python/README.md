# Context Engineering (Python)

This directory contains two Python surfaces:

- `context_engineering`: core context-packing, token budgeting, memory stores, and CLI.
- `context_framework`: tri-provider orchestration and production-style domain runtimes.

## Setup

```bash
cd python
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Core SDK (`context_engineering`)

### Core Functions

| Export                                                                                                                                       | Description                                                   |
| -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `pack(items, budget, *, allow_compression=True, provider=None, weights=None, redundancy_threshold=None, redundancy_config=None, query=None)` | Greedy score-based context packing into a token budget        |
| `trace_pack(items, budget, *, allow_compression=True, provider=None, weights=None, redundancy_threshold=None)`                               | Pack with step-by-step decision trace for debugging           |
| `diff(before, after)`                                                                                                                        | Compare two packs or item arrays (added/removed/kept/changed) |
| `estimate_tokens(text=None, provider=None, model=None)`                                                                                      | Token count estimation (heuristic or tiktoken)                |
| `simulate_budgets(items, min_budget, max_budget, step=100, **kwargs)`                                                                        | Run pack across a budget range                                |
| `to_context_item(memory, options?)`                                                                                                          | Convert a `MemoryItem` to a scored `ContextItem`              |
| `memory_to_context(memories, options?)`                                                                                                      | Batch convert `MemoryItem[]` to `ContextItem[]`               |
| `place_items(items, strategy?, model?)`                                                                                                      | Reorder items for optimal model attention placement           |
| `effective_budget(tokens, model?)`                                                                                                           | De-rate token budget based on model attention degradation     |
| `analyze_context(items)`                                                                                                                     | Quality metrics: density, diversity, freshness, redundancy    |
| `analyze_context_pack(pack)`                                                                                                                 | Quality metrics for a `ContextPack`                           |
| `create_context_manager(budget, ...)`                                                                                                        | Automatic context compaction manager for multi-turn agents    |
| `create_cached_estimator(estimator, max_size?)`                                                                                              | LRU-cached wrapper around any token estimator                 |
| `pack_stream(items, budget, ...)`                                                                                                            | Async generator variant of `pack` — yields items as selected  |

### Cache Topology

| Export                                         | Description                             |
| ---------------------------------------------- | --------------------------------------- |
| `pack_with_cache_topology(items, budget, ...)` | Pack with stable prefix for cache reuse |
| `classify_volatility(item)`                    | Classify item as static/session/request |

### Budget Allocation

| Export                                                  | Description                                           |
| ------------------------------------------------------- | ----------------------------------------------------- |
| `pack_with_allocation(items, budget, allocations, ...)` | Per-kind budget allocation with min/max/target ratios |

### Sessions

| Export                        | Description                                         |
| ----------------------------- | --------------------------------------------------- |
| `create_session(budget, ...)` | Stateful context session with differential tracking |

### Pipeline

| Export                    | Description                                         |
| ------------------------- | --------------------------------------------------- |
| `create_pipeline(budget)` | Composable pipeline builder chaining all operations |

### Cost Estimation

| Export                                   | Description                                               |
| ---------------------------------------- | --------------------------------------------------------- |
| `estimate_cost(pack, model, ...)`        | Per-request cost with cache savings                       |
| `project_costs(pack, model, count, ...)` | Multi-request projection with monthly estimates           |
| `MODEL_PRICING`                          | Built-in pricing for Claude, GPT-4.1, GPT-4o, o3, o4-mini |

### BEADS Agent Handoff

| Export                                 | Description                              |
| -------------------------------------- | ---------------------------------------- |
| `create_handoff(pack, ...)`            | Serialize context pack to BEADS JSONL    |
| `pickup_handoff(jsonl)`                | Recover context items from BEADS JSONL   |
| `context_item_to_beads(item, ...)`     | Convert ContextItem to BEADS issue       |
| `beads_to_context_item(issue)`         | Convert BEADS issue back to ContextItem  |
| `read_beads_jsonl(input)`              | Parse BEADS JSONL string                 |
| `write_beads_jsonl(issues)`            | Serialize BEADS issues to JSONL          |
| `merge_beads_jsonl(existing, updates)` | Merge BEADS JSONL by ID                  |
| `get_ready_issues(issues)`             | Filter to ready (open, unblocked) issues |

### Types

| Export             | Description                                                                                                                                                       |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ContextItem`      | Input item with `id`, `content`, `priority`, `recency`, `compressions`, `kind`, `tokens`, `score`, `metadata`, `embedding`, `task_id`, `is_outcome`, `depends_on` |
| `Budget`           | `max_tokens`, optional `reserve_tokens`                                                                                                                           |
| `ContextPack`      | Pack result with `selected`, `dropped`, `total_tokens`, `stats`                                                                                                   |
| `ContextTrace`     | Trace result with `pack`, `steps[]`, `created_at`                                                                                                                 |
| `ScoringWeights`   | `priority`, `recency`, `salience` weights for scoring                                                                                                             |
| `MemoryItem`       | Memory store item with `id`, `content`, `salience`, `created_at`                                                                                                  |
| `BridgeOptions`    | Memory-to-item options: `priority`, `recency_half_life`, `now`, `kind`                                                                                            |
| `AttentionProfile` | Model attention curve: `name`, `effective_capacity`, `position_weights`                                                                                           |
| `ContextQuality`   | Quality metrics: `density`, `diversity`, `freshness`, `redundancy`, `overall`                                                                                     |
| `CacheAwarePack`   | Extends ContextPack with `cache_key`, `cacheable_tokens`, `cache_efficiency`                                                                                      |
| `AllocatedPack`    | Extends ContextPack with per-kind allocation results                                                                                                              |
| `SessionPack`      | Session compile result with differential `delta`                                                                                                                  |
| `PipelineResult`   | Pipeline output with all stage metadata                                                                                                                           |
| `CostEstimate`     | Per-request cost breakdown with cache savings                                                                                                                     |
| `CostProjection`   | Multi-request projection with monthly estimates                                                                                                                   |
| `BeadsIssue`       | BEADS issue type for agent handoff                                                                                                                                |
| `KindAllocation`   | Per-kind budget: `kind`, `target_ratio`, `min_ratio?`, `max_ratio?`                                                                                               |
| `Turn`             | Conversation turn: `role`, `content`, `tokens`, `is_summary`                                                                                                      |
| `ContextManager`   | Compaction manager: `add_turn()`, `add_items()`, `compile()`, `get_token_usage()`                                                                                 |

### Memory Stores

| Export                | Description                                                     |
| --------------------- | --------------------------------------------------------------- |
| `InMemoryStore`       | Dict-based, no persistence                                      |
| `FileStore`           | JSONL file-backed store                                         |
| `SqliteStore`         | SQLite-backed store with embeddings                             |
| `RedisMemoryStore`    | Redis-backed store (requires `redis` optional dependency)       |
| `PostgresMemoryStore` | Postgres-backed store (requires `postgres` optional dependency) |

### Quick Start

```python
from context_engineering import (
    pack, Budget, ContextItem,
    to_context_item, memory_to_context,
    place_items, effective_budget,
    analyze_context, create_context_manager,
    InMemoryStore, MemoryItem,
)

# 1. Store and retrieve memories
store = InMemoryStore()
store.put([
    MemoryItem(id="arch", content="System uses event sourcing", created_at="2024-01-15T10:00:00Z", salience=0.95),
    MemoryItem(id="perf", content="P99 must stay under 200ms", created_at="2024-01-15T10:00:00Z", salience=0.80),
])
memories = store.query()

# 2. Bridge memories to context items
items = memory_to_context(memories)

# 3. Pack within token budget
budget = effective_budget(128000, "claude")  # 89600 effective
packed = pack(items, Budget(max_tokens=budget))

# 4. Position-aware placement
placed = place_items(packed.selected, strategy="attention-optimized", model="claude")

# 5. Quality metrics
quality = analyze_context(packed.selected)
print(f"Overall quality: {quality.overall}")

# 6. Multi-turn compaction
mgr = create_context_manager(Budget(max_tokens=8000), system_prompt="You are a code reviewer.")
mgr.add_turn("user", "Review this pull request")
mgr.add_turn("assistant", "I see several issues...")
compiled = mgr.compile()
```

### CLI

```bash
# Core commands
ce pack -i items.json -b 4096
ce trace -i items.json -b 4096
ce diff --before before.json --after after.json
ce budget -t "hello world" -p openai
ce lint -s context-item -i items.jsonl

# Placement & quality
ce place -i items.json -s attention-optimized -m claude
ce quality -i items.json
ce effective-budget -t 128000 -m claude

# Agent handoff (BEADS)
ce handoff -i items.json -b 8000 -o .beads/issues.jsonl --agent agent-1
ce pickup -i .beads/issues.jsonl --ready

# Cost estimation
ce cost -i items.json -m claude-sonnet-4-6 --requests 10000 --requests-per-day 500
```

### Additional Exports

The SDK also exports the following modules. These are not covered in full above but are available for advanced use:

- **Error types:** `ContextEngineeringError`, `ValidationError`, `BudgetExceededError`, `EstimationError` -- structured exceptions for all failure modes
- **BM25 search:** `BM25Index`, `create_bm25_index` -- term-frequency keyword search over context items
- **Redundancy:** `RedundancyEliminator`, `eliminate_redundancy_sync` -- detect and remove near-duplicate items
- **Relevance:** `compute_relevance`, `QueryContext` -- query-aware relevance scoring
- **Providers:** `OpenAIProvider`, `AnthropicProvider`, `CerebrasProvider`, `create_llm_summarizer` -- LLM provider adapters for compression/summarization
- **Template:** `compile_to_messages`, `format_for_anthropic`, `format_for_openai` -- convert context packs to provider-specific message arrays
- **Webhook:** `WebhookReporter`, `create_webhook_reporter` -- send packing telemetry to external endpoints

## Tri-Provider Framework (`context_framework`)

`context_framework` includes:

- Provider adapters and SDK bridges for OpenAI, Anthropic, and Cerebras.
- Ollama adapters/bridges for both native local API and OpenAI-compatible cloud mode.
- Framework bridges for LangGraph, Deep Agents, and PydanticAI.
- Anthropic agentic text-operation system with deterministic tool-server utilities.
- Pluggable vector retrieval adapters.
- Rolling context summarization support.
- Tri-provider use-case pipeline definitions.
- Production runtime commanders with:
  - signal extraction
  - adapter enrichment
  - decision routing
  - idempotent action execution
  - retry/backoff logic
  - audit logging

## Production Runtime Scripts

From `python/`:

### 1. SOC Incident Commander

```bash
python examples/soc_incident_commander_runtime.py --mode dry --json
python examples/soc_incident_commander_runtime.py --mode live --use-http-adapters --audit-log /tmp/soc-audit.jsonl
```

### 2. Catastrophe Claims

```bash
python examples/catastrophe_claims_runtime.py --mode dry --json
python examples/catastrophe_claims_runtime.py --mode live --use-http-adapters --audit-log /tmp/claims-audit.jsonl
```

### 3. Supply Chain Control Tower

```bash
python examples/supply_chain_control_tower_runtime.py --mode dry --json
python examples/supply_chain_control_tower_runtime.py --mode live --use-http-adapters --audit-log /tmp/supply-audit.jsonl
```

### 4. AML/KYC Fincrime

```bash
python examples/aml_kyc_fincrime_runtime.py --mode dry --json
python examples/aml_kyc_fincrime_runtime.py --mode live --use-http-adapters --audit-log /tmp/aml-audit.jsonl
```

### 5. Pharmacovigilance Events

```bash
python examples/pharmacovigilance_events_runtime.py --mode dry --json
python examples/pharmacovigilance_events_runtime.py --mode live --use-http-adapters --audit-log /tmp/pv-audit.jsonl
```

### 6. Grid Outage Response

```bash
python examples/grid_outage_response_runtime.py --mode dry --json
python examples/grid_outage_response_runtime.py --mode live --use-http-adapters --audit-log /tmp/grid-audit.jsonl
```

### 7. Emergency Operations Center

```bash
python examples/emergency_operations_center_runtime.py --mode dry --json
python examples/emergency_operations_center_runtime.py --mode live --use-http-adapters --audit-log /tmp/eoc-audit.jsonl
```

### 8. Manufacturing Root Cause and Recovery

```bash
python examples/manufacturing_root_cause_runtime.py --mode dry --json
python examples/manufacturing_root_cause_runtime.py --mode live --use-http-adapters --audit-log /tmp/mfg-audit.jsonl
```

### 9. Regulatory Change Impact

```bash
python examples/regulatory_change_impact_runtime.py --mode dry --json
python examples/regulatory_change_impact_runtime.py --mode live --use-http-adapters --audit-log /tmp/reg-audit.jsonl
```

### 10. Contract Risk Negotiation

```bash
python examples/contract_risk_negotiation_runtime.py --mode dry --json
python examples/contract_risk_negotiation_runtime.py --mode live --use-http-adapters --audit-log /tmp/contract-audit.jsonl
```

### 11. Legacy-to-Modern Migration Factory

```bash
python examples/legacy_modern_migration_runtime.py --mode dry --json
python examples/legacy_modern_migration_runtime.py --mode live --use-http-adapters --audit-log /tmp/migration-audit.jsonl
```

### 12. Contact Center Resolution Autopilot

```bash
python examples/contact_center_autopilot_runtime.py --mode dry --json
python examples/contact_center_autopilot_runtime.py --mode live --use-http-adapters --audit-log /tmp/contact-audit.jsonl
```

### 13. Clinical Operations Optimizer

```bash
python examples/clinical_operations_optimizer_runtime.py --mode dry --json
python examples/clinical_operations_optimizer_runtime.py --mode live --use-http-adapters --audit-log /tmp/clinical-audit.jsonl
```

### 14. Cross-Channel Text Governance Orchestrator

```bash
python examples/use_cases/14_text_governance_orchestrator.py --mode dry --json
python examples/use_cases/14_text_governance_orchestrator.py --mode live --json
```

The runtime scripts share common options:

- `--mode dry|live`
- `--scenario "..."`
- `--evidence-file <path>` (repeatable)
- `--json`
- `--max-parallel <n>`

## Use-Case Runner Scripts

Run a single use case:

```bash
python examples/use_cases/09_regulatory_change_impact.py --mode dry --json
```

Run all use cases:

```bash
python examples/use_cases/run_all_use_cases.py --mode dry --json
```

## Cerebras Advanced Scripts

These scripts exercise advanced Cerebras functionality (speculative decoding, perplexity, reasoning controls):

```bash
python examples/cerebras_speculative_decoding_lab.py
python examples/cerebras_perplexity_router.py
python examples/cerebras_reasoning_controls_lab.py
python examples/weird_provider_sdk_features.py
```

For live runs, configure:

- `CEREBRAS_API_KEY`
- optionally `OPENAI_API_KEY`
- optionally `ANTHROPIC_API_KEY`

## Ollama + Framework + Agentic SDK Scripts

```bash
python examples/ollama_local_cloud_bridge_demo.py --mode local --json
python examples/ollama_local_cloud_bridge_demo.py --mode cloud --json
python examples/framework_bridge_lab.py
python examples/anthropic_agentic_text_system.py --mode dry --json
python examples/anthropic_agentic_text_system.py --mode live --method query --json
python examples/anthropic_agentic_text_system.py --mode live --method client --json
python examples/live_integration_harness.py --json
```

For live runs:

- Ollama local: configure `OLLAMA_BASE_URL` and optionally `OLLAMA_MODEL`
- Ollama cloud/OpenAI-compatible endpoint: configure `OLLAMA_BASE_URL`, optionally `OLLAMA_API_KEY`, and use `--mode cloud`
- Anthropic agentic SDK: install either `claude-agent-sdk` (current) or `claude-code-sdk` (legacy)
- Harness gates:
  - `OLLAMA_RUN_LOCAL_SMOKE=1` to run local Ollama call
  - `OLLAMA_RUN_CLOUD_SMOKE=1` to run cloud/OAI-compatible Ollama call
  - `ANTHROPIC_AGENTIC_SMOKE=1` to run Anthropic agentic SDK workflow
  - `TRI_PROVIDER_LIVE_SMOKE=1` (+ `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `CEREBRAS_API_KEY`) for full live tri-provider pipeline smoke
  - optional `OLLAMA_SMOKE_TIMEOUT_SECONDS` to increase/decrease live Ollama check timeout (default `90`)

The live harness auto-discovers available Ollama models via `/api/tags` and `/v1/models` and picks an installed model if `OLLAMA_MODEL` is not set.

## Testing

```bash
pytest -q tests
```
