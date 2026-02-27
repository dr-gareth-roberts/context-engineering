# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-27

### Added

- **Core**: `pack()`, `tracePack()`, `diff()`, `estimateTokens()`, `createContextItem()`, `createScorer()` — the six core functions
- **Cache topology**: `packWithCacheTopology()` for prefix cache optimization with static/session/request volatility classification
- **Allocation**: `packWithAllocation()` for kind-aware budget splits with min/max/target constraints
- **Sessions**: `createSession()` for stateful context with differential tracking
- **Pipeline**: Fluent builder chaining `.add().allocate().cacheTopology().place().qualityGate().build()`
- **Placement**: `placeItems()` with attention profile-aware ordering (claude, gpt4, uniform)
- **Quality**: `analyzeContext()` returning density, diversity, freshness, redundancy scores
- **Cost**: `estimateCost()` and `projectCosts()` with prefix cache savings for Claude and GPT models
- **BEADS handoff**: `createHandoff()` / `pickupHandoff()` for agent-to-agent context serialization
- **Compaction**: `createContextManager()` for auto-summarization across conversation turns
- **Stream**: `packStream()` async generator variant
- **Memory stores** (`@context-engineering/memory`): InMemory, File (JSONL with atomic writes), SQLite
- **Provider adapters** (`@context-engineering/providers`): OpenAI (tiktoken) and Anthropic token estimators
- **CLI** (`@context-engineering/cli`): 11 commands — pack, trace, diff, budget, lint, place, quality, effective-budget, handoff, pickup, cost
- **Python SDK**: Full API parity with TypeScript plus advanced features (negation/supersession, hierarchical inclusion, semantic redundancy, AgentContextManager, segmenters)
- **Error hierarchy**: `ValidationError`, `BudgetExceededError`, `EstimationError` with structured details
- **Shared JSON Schemas** for cross-language validation

[0.1.0]: https://github.com/dr-gareth-roberts/context-engineering/releases/tag/v0.1.0
