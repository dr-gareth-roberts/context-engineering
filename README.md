# Context Engineering Toolkit

[![CI](https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@context-engineering/core)](https://www.npmjs.com/package/@context-engineering/core)
[![PyPI](https://img.shields.io/pypi/v/context-engineering)](https://pypi.org/project/context-engineering/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Dual TypeScript/Python SDKs + CLI for LLM context packing, token budgeting, and cache optimization.

When you're building with LLMs, you need to decide **what context fits** in your prompt given a finite token budget. This toolkit gives you algorithms to pack context intelligently, optimize for prefix caching, estimate costs, and hand off context between agents.

## Quick Start

### TypeScript

```bash
npm install @context-engineering/core
```

```ts
import { pack } from "@context-engineering/core";

const result = pack(
  [
    { id: "docs", content: "API reference...", priority: 8 },
    { id: "history", content: "Previous conversation...", priority: 3 },
    { id: "query", content: "User question", priority: 10 },
  ],
  { maxTokens: 4096 }
);

console.log(result.selected); // items that fit the budget
console.log(result.totalTokens); // tokens used
```

### Python

```bash
pip install context-engineering
```

```python
from context_engineering import pack, Budget, ContextItem

result = pack(
    [
        ContextItem(id="docs", content="API reference...", priority=8),
        ContextItem(id="history", content="Previous conversation...", priority=3),
        ContextItem(id="query", content="User question", priority=10),
    ],
    Budget(maxTokens=4096),
)

print(result.selected)      # items that fit the budget
print(result.total_tokens)  # tokens used
```

### CLI

```bash
npx @context-engineering/cli pack -i items.json -b 4096   # TypeScript
ce pack -i items.json -b 4096                              # Python
```

## Core API

Six functions form the tight center. Everything else builds on these.

| Function                         | What it does                                                                              |
| -------------------------------- | ----------------------------------------------------------------------------------------- |
| `pack(items, budget)`            | Select items that fit a token budget (greedy, score-based)                                |
| `tracePack(items, budget)`       | Pack with per-item decision log                                                           |
| `diff(before, after)`            | Compare two context states (added/removed/kept/changed)                                   |
| `estimateTokens(content)`        | Count tokens (heuristic by default; pluggable for OpenAI/Anthropic via providers package) |
| `createContextItem(id, content)` | Convenience factory for items                                                             |
| `createScorer(weights?)`         | Custom scoring with priority/recency/salience weights                                     |

Scoring formula: `priority * 1.0 + recency * 0.7 + salience * 0.5 + relevance * 0.0` (relevance activates when a query is provided; salience is read from `item.metadata.salience`)

## Extended Features

| Feature               | Entry point                           | Purpose                                                                           |
| --------------------- | ------------------------------------- | --------------------------------------------------------------------------------- |
| **Causal Compaction** | `createCausalScorer(issues)`          | Graph-aware pruning of conversation history ([Docs](./docs/causal-compaction.md)) |
| **Cache Topology**    | `packWithCacheTopology()`             | Partition items by volatility for prefix cache reuse                              |
| **Allocation**        | `packWithAllocation()`                | Kind-aware budget splits with min/max/target constraints                          |
| **Sessions**          | `createSession()`                     | Track what changed between context compiles                                       |
| **Pipeline**          | `pipeline(budget)`                    | Fluent builder: `.add().allocate().cacheTopology().build()`                       |
| **Placement**         | `placeItems()`                        | Reorder items by model attention profile (start/end bias)                         |
| **Quality**           | `analyzeContext()`                    | Density, diversity, freshness, redundancy scores                                  |
| **Cost**              | `estimateCost()`                      | Dollar cost with prefix cache savings                                             |
| **BEADS Handoff**     | `createHandoff()` / `pickupHandoff()` | Serialize/deserialize context for agent-to-agent transfer                         |
| **Compaction**        | `createContextManager()`              | Auto-summarize old turns in conversation                                          |
| **Stream**            | `packStream()`                        | Async generator variant of pack                                                   |

### Pipeline Example

```ts
import { pipeline } from "@context-engineering/core";

const result = pipeline(8000)
  .add(systemPrompt, tools, documents, query)
  .allocate([
    { kind: "system", targetRatio: 0.3 },
    { kind: "retrieval", targetRatio: 0.5 },
    { kind: "query", targetRatio: 0.2 },
  ])
  .cacheTopology({ provider: "anthropic" })
  .place("attention-optimized")
  .qualityGate({ minOverall: 0.5 })
  .build();
```

### Cost Estimation

```ts
import { packWithCacheTopology, estimateCost } from "@context-engineering/core";

const packed = packWithCacheTopology(items, { maxTokens: 8000 });
const cost = estimateCost(packed, "claude-sonnet-4-6");
console.log(
  `Saving $${cost.savings.toFixed(4)} per request (${cost.savingsPercent.toFixed(1)}%)`
);
```

## Architecture

```
packages/
  ce-core/        Core algorithms (pack, diff, trace, place, quality, cost)
  ce-providers/   OpenAI + Anthropic adapters, token estimators
  ce-memory/      Memory stores (InMemory, File, SQLite, Redis)
  ce-cli/         CLI with 11 commands
  ce-web-client/  Interactive playground UI (internal, not published)
  ce-web-server/  Dev server for playground (internal, not published)
python/           Python SDK (full API parity + advanced features)
schemas/          JSON Schemas shared across languages
```

### Memory Stores

```ts
import { createMemoryStore } from "@context-engineering/memory";

const mem = createMemoryStore("memory"); // In-memory
const file = createMemoryStore("file", { path: "mem.jsonl" }); // JSONL with atomic writes
const db = createMemoryStore("sqlite", { path: "db.sqlite" }); // SQLite with WAL
```

All stores implement `put()`, `get()`, `query()`, `forget()`, `close()` with consistent TTL semantics.

### CLI

| Command               | Purpose                        |
| --------------------- | ------------------------------ |
| `ce pack`             | Pack items into a budget       |
| `ce trace`            | Pack with decision trace       |
| `ce diff`             | Compare two context states     |
| `ce budget`           | Estimate token count           |
| `ce lint`             | Validate against JSON Schema   |
| `ce place`            | Attention-optimized placement  |
| `ce quality`          | Context quality analysis       |
| `ce effective-budget` | Budget de-rating for attention |
| `ce handoff`          | Create BEADS agent handoff     |
| `ce pickup`           | Resume from BEADS handoff      |
| `ce cost`             | API cost estimation            |

### Python-Only Features

The Python SDK includes everything above plus:

- **Advanced pack**: negation/supersession, hierarchical inclusion, semantic redundancy detection, relation boosts
- **AgentContextManager**: orchestration with adaptive budgeting, segmentation, memory, handoff
- **Segmenters**: structural, semantic, perplexity, hybrid with boundary protection
- **Budget simulation**: `simulate_budgets()` across a range

## Development

### Prerequisites

- Node.js 18+, pnpm 10+
- Python 3.11+

### Setup

```bash
pnpm install && pnpm build:all              # TypeScript
cd python && pip install -e ".[dev]"         # Python
```

### Testing

```bash
pnpm test:all                               # TypeScript (~700 tests, as of March 2026)
cd python && python -m pytest               # Python (~580 tests, as of March 2026)
pnpm check:all                              # Type checking
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for full development guide.

## Error Handling

All errors inherit from `ContextEngineeringError` with a `code` field:

| Error                 | Code               | When                                                                      |
| --------------------- | ------------------ | ------------------------------------------------------------------------- |
| `ValidationError`     | `VALIDATION_ERROR` | Bad inputs — includes structured `details[].path` and `details[].message` |
| `BudgetExceededError` | `BUDGET_EXCEEDED`  | `reserveTokens >= maxTokens`                                              |
| `EstimationError`     | `ESTIMATION_ERROR` | Unknown model or bad pricing data                                         |

## License

[MIT](./LICENSE)
