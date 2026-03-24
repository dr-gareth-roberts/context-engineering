![Context Engineering Toolkit](./assets/banner.png)

[![CI](https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Most LLM apps waste 30-50% of their context window on redundant, stale, or irrelevant content.** This toolkit treats context as a first-class engineering problem.

17 TypeScript packages with full Python parity. 2,172 tests. [Browse the Wiki](./docs/wiki/Home.md).

---

## The Problem

Every LLM call has a finite context window. You have system prompts, retrieved documents, conversation history, tool definitions, and user queries competing for space. The naive approach — truncate the oldest messages — fails predictably:

- Loses the system prompt after enough turns
- Drops high-value documents randomly
- Wastes budget on stale or redundant items

This toolkit provides **algorithms for deciding what goes in**, with scoring, caching, quality monitoring, adversarial testing, and multi-model orchestration.

## Novel Features

These aren't wrappers around existing APIs — they're new capabilities for managing context:

**Council of Experts** — Multiple LLM models with distinct perspectives (critic, architect, user-advocate) deliberate on a question through [4 structured strategies](./docs/wiki/Deliberation-Strategies.md): parallel, debate, stepladder (prevents anchoring bias), and delphi (anonymous with convergence detection).

**Adversarial Context Tester** — Red-team your context pipeline with [6 attack types](./docs/wiki/Adversarial-Testing.md): contradiction injection, noise flooding, subtle error mutation, authority spoofing, temporal poisoning, and relevance dilution. Catches vulnerabilities before production.

**Context Immune System** — Records failure patterns as fingerprints and develops [antibodies](./docs/wiki/Context-Immune-System.md) that screen future packs. Individual items can be fine but certain _combinations_ are toxic — the immune system learns these.

**Context Compiler** — [Declare what you want](./docs/wiki/Context-Compilation.md), not how to arrange it. Slots, constraints, and per-model optimization passes for Claude, GPT-4, and Gemini. Like a C compiler targeting different architectures.

**Context Entanglement** — A [pub/sub mesh](./docs/wiki/Multi-Agent-Entanglement.md) for multi-agent systems. When Agent A discovers something, Agent B's next `pack()` automatically includes it — with scoped propagation, TTL expiry, and budget-aware injection.

**Drift Detector** — Monitors [6 quality dimensions](./docs/wiki/Drift-Detection.md) (relevance, redundancy, diversity, density, freshness, utilization) across a sliding window. Alerts when your context is silently degrading before the model starts hallucinating.

**Context Time Travel** — [Git for context states](./docs/wiki/Context-Time-Travel.md). Checkpoint, rewind, fork, compare, and merge with 5 strategies (union, intersection, best-quality, highest-priority, manual).

**Semantic Boundary Segmentation** — Split documents at semantic boundaries (topic shifts, structural markers, perplexity spikes) rather than arbitrary token limits. Hybrid segmenters combine structural, semantic, and perplexity signals with boundary protection.

**Cache Topology Optimization** — Orders items by volatility (static/session/request) so the stable prefix stays constant across requests. Up to 90% cost reduction with Anthropic's prefix caching.

**Causal Graph Compaction** — Uses [BEADS task graphs](./docs/causal-compaction.md) to prune conversation history by causal relevance, not recency. Protects root goals and task outcomes while aggressively pruning process noise from closed tasks.

## All Packages

| Category         | Packages                                                                                                                                          | Purpose                                                                |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| **Core**         | [core](./packages/ce-core/) / [providers](./packages/ce-providers/) / [memory](./packages/ce-memory/) / [cli](./packages/ce-cli/)                 | Pack, score, diff, place, quality, cost, cache topology, BEADS handoff |
| **Multi-Model**  | [council](./packages/ce-council/) / [entangle](./packages/ce-entangle/) / [router](./packages/ce-router/)                                         | Experts debate; agents share context; route to cheapest model          |
| **Quality**      | [adversarial](./packages/ce-adversarial/) / [immune](./packages/ce-immune/) / [debugger](./packages/ce-debugger/) / [drift](./packages/ce-drift/) | Red-team; learn from failures; diagnose outputs; monitor degradation   |
| **Optimization** | [compiler](./packages/ce-compiler/) / [adaptive](./packages/ce-adaptive/) / [time-travel](./packages/ce-time-travel/)                             | Declarative compilation; learn weights; checkpoint/fork/merge          |
| **Integration**  | [sdk-interceptors](./packages/ce-sdk-interceptors/) / [frameworks](./packages/ce-frameworks/) / [rag](./packages/ce-rag/)                         | OpenAI/Anthropic wrappers; LangChain middleware; info-gain retrieval   |

## Install

```bash
npm install @context-engineering/core    # TypeScript
pip install context-engineering          # Python (pydantic-only core — extras for providers, CLI, etc.)
```

## Quick Start

```ts
import { pack } from "@context-engineering/core";

const result = pack(
  [
    { id: "system", content: "You are a helpful assistant.", priority: 10 },
    { id: "docs", content: "API reference documentation...", priority: 7 },
    { id: "history", content: "Previous conversation...", priority: 3 },
    { id: "query", content: "How do I authenticate?", priority: 9 },
  ],
  { maxTokens: 4096 }
);
// result.selected — items that fit, scored and sorted
// result.dropped  — items that didn't make the cut
```

### Pipeline

```ts
const result = pipeline(8000)
  .add(systemPrompt, tools, documents)
  .allocate([
    { kind: "system", targetRatio: 0.15 },
    { kind: "retrieval", targetRatio: 0.55 },
    { kind: "conversation", targetRatio: 0.3 },
  ])
  .cacheTopology({ provider: "anthropic" })
  .qualityGate({ minOverall: 0.5 })
  .build();
```

### Council of Experts

```ts
const council = createCouncil({
  members: [
    {
      id: "arch",
      name: "Architect",
      ...ROLE_PRESETS.pragmatist,
      provider: anthropic,
    },
    { id: "sec", name: "Security", ...ROLE_PRESETS.critic, provider: openai },
  ],
  strategy: "debate",
  rounds: 2,
  synthesizer: { provider: anthropic },
});

const result = await council.deliberate({
  query: "Microservices or monolith?",
});
```

## Examples

Runnable demos — no API keys needed:

| Example                                                | What it shows                                          |
| ------------------------------------------------------ | ------------------------------------------------------ |
| [RAG Chatbot](./examples/rag-chatbot/)                 | Retrieval + info-gain filtering + pipeline packing     |
| [Code Review Council](./examples/code-review-council/) | 3 experts debate a PR with convergence scoring         |
| [Production Agent](./examples/production-agent/)       | Drift detection + time-travel recovery + immune system |

```bash
npx tsx examples/rag-chatbot/index.ts
npx tsx examples/code-review-council/index.ts
npx tsx examples/production-agent/index.ts
```

## Development

```bash
pnpm install && pnpm build:all              # TypeScript (1,264 tests across 17 packages)
cd python && pip install -e ".[dev]"        # Python (908 tests)
pnpm test:packages                          # Run all TS tests
python -m pytest                            # Run all Python tests
```

See [CONTRIBUTING.md](./CONTRIBUTING.md). Browse the [Wiki](./docs/wiki/Home.md) for architecture and deep dives.

## License

[MIT](./LICENSE)
