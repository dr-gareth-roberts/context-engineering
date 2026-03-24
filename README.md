<p align="center">
  <img src="./assets/banner.svg" alt="Context Engineering Toolkit" width="100%">
</p>

<p align="center">
  <a href="https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml"><img src="https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.npmjs.com/package/@context-engineering/core"><img src="https://img.shields.io/npm/v/@context-engineering/core" alt="npm"></a>
  <a href="https://pypi.org/project/context-engineering/"><img src="https://img.shields.io/pypi/v/context-engineering" alt="PyPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
</p>

**Most LLM applications waste 30-50% of their context window on redundant, stale, or irrelevant content.** This costs real money at scale — and degrades output quality silently.

This toolkit fixes that. It gives you algorithms to **pack context intelligently** (greedy score-based selection), **optimize for prefix caching** (up to 90% cost reduction with Anthropic), **red-team your pipeline** (6 adversarial attack types), **have multiple models debate** (Council of Experts with 4 strategies), and **share context across agents** (entanglement mesh) — all in both TypeScript and Python with full API parity.

> **17 packages** | **2,172 tests** | **Dual TS/Python** | [Wiki](./docs/wiki/Home.md)

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

## Packages

### Core

| Package                                    | What it does                                                               |
| ------------------------------------------ | -------------------------------------------------------------------------- |
| [`ce-core`](./packages/ce-core/)           | Pack, score, diff, place, quality, cost, sessions, pipeline, BEADS handoff |
| [`ce-providers`](./packages/ce-providers/) | OpenAI + Anthropic adapters, token estimators                              |
| [`ce-memory`](./packages/ce-memory/)       | Memory stores (InMemory, File, SQLite, Redis)                              |
| [`ce-cli`](./packages/ce-cli/)             | CLI with 11 commands                                                       |

### Multi-Model & Multi-Agent

| Package                                  | What it does                                                           |
| ---------------------------------------- | ---------------------------------------------------------------------- |
| [`ce-council`](./packages/ce-council/)   | Council of Experts — multi-model deliberation with 4 debate strategies |
| [`ce-entangle`](./packages/ce-entangle/) | Context Entanglement — pub/sub mesh for multi-agent context sharing    |
| [`ce-router`](./packages/ce-router/)     | Route to cheapest model by context complexity                          |

### Quality & Safety

| Package                                        | What it does                                                           |
| ---------------------------------------------- | ---------------------------------------------------------------------- |
| [`ce-adversarial`](./packages/ce-adversarial/) | Red-team context pipelines with 6 attack types                         |
| [`ce-immune`](./packages/ce-immune/)           | Learn from failures, develop antibodies against toxic context patterns |
| [`ce-debugger`](./packages/ce-debugger/)       | Diagnose bad model outputs via context analysis                        |
| [`ce-drift`](./packages/ce-drift/)             | Monitor context quality degradation over time                          |

### Optimization

| Package                                        | What it does                                           |
| ---------------------------------------------- | ------------------------------------------------------ |
| [`ce-compiler`](./packages/ce-compiler/)       | Declarative context programs compiled per target model |
| [`ce-adaptive`](./packages/ce-adaptive/)       | Adaptive weight learning from outcome feedback         |
| [`ce-time-travel`](./packages/ce-time-travel/) | Git-like checkpoint/fork/merge for context states      |

### Integration

| Package                                                  | What it does                                    |
| -------------------------------------------------------- | ----------------------------------------------- |
| [`ce-sdk-interceptors`](./packages/ce-sdk-interceptors/) | Drop-in wrappers for OpenAI/Anthropic SDKs      |
| [`ce-frameworks`](./packages/ce-frameworks/)             | Middleware for LangChain, LlamaIndex, CrewAI    |
| [`ce-rag`](./packages/ce-rag/)                           | Context-aware RAG with information gain scoring |

All packages have full **Python parity** in the [`python/`](./python/) directory.

## Core API

Six functions form the tight center. Everything else builds on these.

| Function                         | What it does                                                   |
| -------------------------------- | -------------------------------------------------------------- |
| `pack(items, budget)`            | Select items that fit a token budget (greedy, score-based)     |
| `tracePack(items, budget)`       | Pack with per-item decision log                                |
| `diff(before, after)`            | Compare two context states (added/removed/kept/changed)        |
| `estimateTokens(content)`        | Count tokens (heuristic; pluggable for tiktoken via providers) |
| `createContextItem(id, content)` | Convenience factory for items                                  |
| `createScorer(weights?)`         | Custom scoring with priority/recency/salience weights          |

Scoring formula: `priority * 1.0 + recency * 0.7 + salience * 0.5 + relevance * 0.0` (relevance activates when a query is provided)

## Extended Features

| Feature               | Entry point                           | Purpose                                                                           |
| --------------------- | ------------------------------------- | --------------------------------------------------------------------------------- |
| **Pipeline**          | `pipeline(budget)`                    | Fluent builder: `.add().allocate().cacheTopology().build()`                       |
| **Cache Topology**    | `packWithCacheTopology()`             | Partition items by volatility for prefix cache reuse                              |
| **Allocation**        | `packWithAllocation()`                | Kind-aware budget splits with min/max/target constraints                          |
| **Placement**         | `placeItems()`                        | Reorder items by model attention profile (start/end bias)                         |
| **Quality**           | `analyzeContext()`                    | Density, diversity, freshness, redundancy scores                                  |
| **Cost**              | `estimateCost()`                      | Dollar cost with prefix cache savings                                             |
| **BEADS Handoff**     | `createHandoff()` / `pickupHandoff()` | Serialize/deserialize context for agent-to-agent transfer                         |
| **Causal Compaction** | `createCausalScorer(issues)`          | Graph-aware pruning of conversation history ([Docs](./docs/causal-compaction.md)) |
| **Sessions**          | `createSession()`                     | Track what changed between context compiles                                       |
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

### Council of Experts

```ts
import { createCouncil, ROLE_PRESETS } from "@context-engineering/council";

const council = createCouncil({
  members: [
    {
      id: "arch",
      name: "Architect",
      ...ROLE_PRESETS.pragmatist,
      provider: anthropic,
    },
    { id: "sec", name: "Security", ...ROLE_PRESETS.critic, provider: openai },
    {
      id: "ux",
      name: "UX",
      ...ROLE_PRESETS["user-advocate"],
      provider: anthropic,
    },
  ],
  strategy: "debate", // or "parallel", "stepladder", "delphi"
  rounds: 2,
  synthesizer: { provider: anthropic },
});

const result = await council.deliberate({
  query: "Microservices or modular monolith?",
  contextItems: architectureDocs,
  budget: { maxTokens: 8000 },
});
```

### Adversarial Testing

```ts
import { createAdversarialTester } from "@context-engineering/adversarial";

const tester = createAdversarialTester({
  attacks: ["contradiction", "noise-flood", "subtle-error", "authority-spoof"],
});

const report = await tester.probe(items, budget, async packed => {
  const response = await llm.generate(packed);
  return evaluateQuality(response); // 0-1
});
// report.overall: "resilient" | "vulnerable" | "critical"
```

### Context Compiler

```ts
import {
  contextProgram,
  createContextCompiler,
} from "@context-engineering/compiler";

const program = contextProgram()
  .declare("goal", { kind: "system", required: true, position: "first" })
  .declare("tools", { kind: "tool", required: true })
  .declare("docs", {
    kind: "retrieval",
    fillRemaining: true,
    deduplicate: true,
  })
  .constraint("coverage")
  .constraint("max-redundancy", { threshold: 0.3 })
  .build();

const compiled = createContextCompiler().compile(program, {
  target: "claude",
  items: allItems,
  budget: { maxTokens: 100000 },
});
```

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
pnpm test:all                               # TypeScript (1,264 tests across 17 packages)
cd python && python -m pytest               # Python (908 tests)
pnpm check:all                              # Type checking
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for full development guide.

## Why Not Just Truncate?

The naive approach — `messages.slice(-N)` or LangChain's `ConversationBufferWindowMemory` — drops the oldest content. This fails in predictable ways:

| Approach                    | What goes wrong                                                    |
| --------------------------- | ------------------------------------------------------------------ |
| **Truncate oldest**         | Loses the original goal/system prompt after enough turns           |
| **Truncate by token count** | No awareness of what's important — drops high-value items randomly |
| **Fixed window**            | Wastes budget on stale/redundant items while cutting relevant ones |

This toolkit scores every item by priority, recency, and relevance, then selects the combination that maximizes value within budget. It also:

- **Optimizes for cache reuse** — orders items so the stable prefix stays constant across requests (up to 90% cost reduction)
- **Allocates by category** — "50% retrieval, 30% conversation, 20% system" ensures no single category dominates
- **Detects quality degradation** — alerts when your context is silently losing coherence
- **Red-teams your pipeline** — discovers which attack patterns (contradictions, noise, spoofing) break your system before users do

## Examples

Runnable example apps showing real use cases (no API keys needed):

| Example                                                | What it shows                                                                    | Run                                             |
| ------------------------------------------------------ | -------------------------------------------------------------------------------- | ----------------------------------------------- |
| [RAG Chatbot](./examples/rag-chatbot/)                 | Retrieval → information-gain filtering → pipeline packing                        | `npx tsx examples/rag-chatbot/index.ts`         |
| [Code Review Council](./examples/code-review-council/) | 3 experts debate a code change (architect, security, performance)                | `npx tsx examples/code-review-council/index.ts` |
| [Production Agent](./examples/production-agent/)       | Drift monitoring → time travel recovery → adversarial testing → immune screening | `npx tsx examples/production-agent/index.ts`    |

## Error Handling

All errors inherit from `ContextEngineeringError` with a `code` field:

| Error                 | Code               | When                                                                      |
| --------------------- | ------------------ | ------------------------------------------------------------------------- |
| `ValidationError`     | `VALIDATION_ERROR` | Bad inputs — includes structured `details[].path` and `details[].message` |
| `BudgetExceededError` | `BUDGET_EXCEEDED`  | `reserveTokens >= maxTokens`                                              |
| `EstimationError`     | `ESTIMATION_ERROR` | Unknown model or bad pricing data                                         |

## License

[MIT](./LICENSE)
