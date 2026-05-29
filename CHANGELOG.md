# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **SDK Interceptors** (`@context-engineering/sdk-interceptors`): Drop-in context management wrappers for OpenAI and Anthropic SDKs — intercept API calls and automatically pack messages within budget
- **Adaptive Learning** (`@context-engineering/adaptive`): Observes which context items correlate with good model outputs and adjusts scoring weights over time via EMA-based feedback loops
- **Framework Middleware** (`@context-engineering/frameworks`): Duck-typed middleware for LangChain, LlamaIndex, and CrewAI — zero framework dependencies
- **Context Debugger** (`@context-engineering/debugger`): Diagnoses bad model outputs by tracing them to context quality problems (missing context, redundancy, stale items, budget waste)
- **Context-Aware RAG** (`@context-engineering/rag`): Retrieves chunks based on information gain relative to existing context, not just similarity — supports hybrid vector + BM25 retrieval
- **Model Router** (`@context-engineering/router`): Analyses context complexity across six dimensions and routes to the cheapest capable model, with adaptive learning and quality-based fallback
- **Context Replay**: Record pack decisions and replay with different strategies for A/B testing
- **Context Inspector**: Web UI for debugging context windows (internal)
- **Council of Experts** (`@context-engineering/council`): Multi-model deliberation with 4 strategies (parallel, debate, stepladder, delphi), 8 role presets, Jaccard convergence detection
- **Adversarial Tester** (`@context-engineering/adversarial`): Red-team context pipelines with 6 attack types (contradiction, noise-flood, subtle-error, authority-spoof, temporal-poison, relevance-dilution)
- **Context Time Travel** (`@context-engineering/time-travel`): Git-like checkpoint/rewind/fork/merge for context states with 5 merge strategies (union, intersection, best-quality, highest-priority, manual)
- **Drift Detector** (`@context-engineering/drift`): Continuous monitoring across 6 dimensions (relevance, redundancy, diversity, density, freshness, utilisation) with trend detection and alerting
- **Context Immune System** (`@context-engineering/immune`): Learns from context failures via fingerprint-based similarity matching, generates antibodies to screen future packs
- **Context Compiler** (`@context-engineering/compiler`): Declarative context programs with slot-based allocation, constraint validation, and per-model optimisation (Claude, GPT-5.4, Gemini 2.5)
- **Context Entanglement** (`@context-engineering/entangle`): Multi-agent context sharing via scoped pub/sub mesh with propagation policies (immediate, next-pack, on-demand)
- **Python parity**: All packages ported to Python with full API surface

### Changed

- **Pipeline**: Eliminated sync/async code duplication using the `MaybeAsync` pattern — `build()` and `buildAsync()` now share a single implementation
- **Provider adapters**: Use properly typed SDK params (`ChatCompletionCreateParamsNonStreaming`, `MessageCreateParamsNonStreaming`) instead of `Record<string, unknown>` casts — fixes type checking against latest OpenAI/Anthropic SDK versions
- **Python `context_framework`**: Domain runtime modules now use lazy imports via `__getattr__` — importing the package no longer eagerly loads all 12 runtime modules

### Fixed

- Type errors in `ce-providers` caused by OpenAI/Anthropic SDK union return types (`Stream | ChatCompletion`)
- Harmonised vitest versions across all packages (^4.1.0)

## [0.1.0] - 2026-02-27

### Added

- **Core**: `pack()`, `tracePack()`, `diff()`, `estimateTokens()`, `createContextItem()`, `createScorer()` — the six core functions
- **Cache topology**: `packWithCacheTopology()` for prefix cache optimisation with static/session/request volatility classification
- **Allocation**: `packWithAllocation()` for kind-aware budget splits with min/max/target constraints
- **Sessions**: `createSession()` for stateful context with differential tracking
- **Pipeline**: Fluent builder chaining `.add().allocate().cacheTopology().place().qualityGate().build()`
- **Placement**: `placeItems()` with attention profile-aware ordering (claude, gpt4, uniform)
- **Quality**: `analyzeContext()` returning density, diversity, freshness, redundancy scores
- **Cost**: `estimateCost()` and `projectCosts()` with prefix cache savings for Claude and GPT models
- **BEADS handoff**: `createHandoff()` / `pickupHandoff()` for agent-to-agent context serialisation
- **Compaction**: `createContextManager()` for auto-summarisation across conversation turns
- **Stream**: `packStream()` async generator variant
- **Memory stores** (`@context-engineering/memory`): InMemory, File (JSONL with atomic writes), SQLite
- **Provider adapters** (`@context-engineering/providers`): OpenAI (tiktoken) and Anthropic token estimators
- **CLI** (`@context-engineering/cli`): 11 commands — pack, trace, diff, budget, lint, place, quality, effective-budget, handoff, pickup, cost
- **Python SDK**: Full API parity with TypeScript plus advanced features (negation/supersession, hierarchical inclusion, semantic redundancy, `AgentContextManager`, segmenters)
- **Error hierarchy**: `ValidationError`, `BudgetExceededError`, `EstimationError` with structured details
- **Shared JSON Schemas** for cross-language validation

[0.1.0]: https://github.com/dr-gareth-roberts/context-engineering/releases/tag/v0.1.0
