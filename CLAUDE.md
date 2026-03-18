# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Context Engineering Toolkit — dual TypeScript/Python SDKs + CLI for LLM context packing, token budgeting, and cache optimization. JSON schemas shared across languages.

## Commands

```bash
# Testing (353 TS + 487 Python = 840 tests)
pnpm test:all                           # All TS package tests (Vitest)
cd packages/ce-core && npx vitest run   # Single package
npx vitest run src/pack.test.ts         # Single file (from package dir)
cd python && python -m pytest           # All Python tests
cd python && python -m pytest tests/test_core.py  # Single file

# Type checking
pnpm check:all    # TypeScript strict mode across all packages

# Building
pnpm build:all    # Build all workspace packages (tsc per package)
pnpm build        # Build frontend (Vite) + bundle server (esbuild)

# Python
cd python && pip install -e ".[dev]"    # Install for development
```

## Architecture

### Monorepo Layout

```
packages/ce-core       Core algorithms — the tight center of the toolkit
packages/ce-memory     Memory stores: InMemoryStore, FileStore (JSONL), SqliteStore
packages/ce-providers  OpenAI + Anthropic adapters, token estimators
packages/ce-cli        CLI (`ce`) — 11 commands, TTY-aware output
packages/ce-web-client React 19 docs + demos web app
packages/ce-web-server Minimal Express server for the web app
python/                Python SDK — shares core API with TS + Python-only extras
schemas/               JSON Schemas shared across languages
```

### Package Dependencies

```
ce-cli → ce-core, ce-providers
ce-providers → ce-core
ce-memory → ce-core
```

## Core API (the tight center)

These 6 functions + 4 types + 4 errors are the essential API. Everything else builds on these.

### Functions

| Function                                         | What it does                         | Key behavior                                                                                                            |
| ------------------------------------------------ | ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| **`pack(items, budget, options?)`**              | Select items that fit a token budget | Greedy score-based. Score = priority×1.0 + recency×0.7 + salience×0.5. Validates inputs via Zod. Supports compressions. |
| **`tracePack(items, budget, options?)`**         | Pack with decision log               | Returns `ContextTrace` with per-item include/compress/exclude decisions and reasons.                                    |
| **`diff(before, after)`**                        | Compare two context states           | Returns added, removed, kept, changed items.                                                                            |
| **`estimateTokens(content, options?)`**          | Count tokens                         | Heuristic (words×1.3), OpenAI (tiktoken), or Anthropic (words×1.4). Returns 0 for empty input.                          |
| **`createContextItem(id, content, overrides?)`** | Create an item                       | Convenience factory — only id + content required.                                                                       |
| **`createScorer(weights?)`**                     | Custom scoring                       | Weights: `{ priority, recency, salience }`. Returns scorer function.                                                    |

### Types

```ts
ContextItem { id, content, kind?, priority?, recency?, tokens?, score?, metadata?, compressions? }
Budget { maxTokens, reserveTokens? }
ContextPack { budget, selected[], dropped[], totalTokens }
PackOptions { scorer?, tokenEstimator?, summarizer?, weights?, logger? }
```

### Errors (both TS and Python)

All inherit from `ContextEngineeringError` with a `code` field:

- **`ValidationError`** (`VALIDATION_ERROR`) — bad inputs, with structured `details[].path` and `details[].message`
- **`BudgetExceededError`** (`BUDGET_EXCEEDED`) — reserveTokens >= maxTokens
- **`EstimationError`** (`ESTIMATION_ERROR`) — unknown model, bad pricing

## Extended Features (built on core)

Each extends the core pack/item model. Use when needed, ignore when not.

| Feature            | Entry point                           | Purpose                                                             |
| ------------------ | ------------------------------------- | ------------------------------------------------------------------- |
| **Cache topology** | `packWithCacheTopology()`             | Partition items by volatility for prefix cache reuse                |
| **Allocation**     | `packWithAllocation()`                | Kind-aware budget splits with min/max/target constraints            |
| **Sessions**       | `createSession()`                     | Track what changed between compiles (delta, reuse ratio)            |
| **Pipeline**       | `pipeline(budget)`                    | Fluent builder chaining `.add().allocate().cacheTopology().build()` |
| **Placement**      | `placeItems()`                        | Reorder items by model attention profile (start/end bias)           |
| **Quality**        | `analyzeContext()`                    | Density, diversity, freshness, redundancy scores                    |
| **Cost**           | `estimateCost()`                      | Dollar cost with prefix cache savings (Claude, GPT pricing)         |
| **BEADS handoff**  | `createHandoff()` / `pickupHandoff()` | Serialize/deserialize context as BEADS JSONL for agent handoff      |
| **Compaction**     | `createContextManager()`              | Auto-summarize old turns across conversation                        |
| **Stream**         | `packStream()`                        | Async generator variant of pack                                     |
| **Bridge**         | `toContextItem()`                     | Convert MemoryItems to ContextItems                                 |
| **Caching**        | `createCachedEstimator()`             | LRU cache for token estimators                                      |

### Memory Stores (`@context-engineering/memory`)

```ts
createMemoryStore("memory"); // In-memory
createMemoryStore("file", { path: "mem.jsonl" }); // JSONL with atomic writes
createMemoryStore("sqlite", { path: "db.sqlite" }); // SQLite
```

Interface: `put()`, `get()`, `query()`, `forget()`, `close?()`

### CLI (`ce`) — 11 commands

TTY-aware: colors when interactive, JSON when piped. Reads `CE_BUDGET` and `CE_PROVIDER` env vars.

Core: `pack`, `trace`, `diff`, `budget`, `lint`
Extended: `place`, `quality`, `effective-budget`, `handoff`, `pickup`, `cost`

Python CLI: `python -m context_engineering <command>` — full parity.

### Python-only features (not in TS)

- **Advanced pack**: Negation/supersession, hierarchical inclusion, semantic redundancy detection, relation boosts, `simulate_budgets()`
- **AgentContextManager** (`framework.py`): Orchestration with adaptive budgeting, segmentation, memory, handoff
- **Segmenters** (`segmentation.py`): Structural, Semantic, Perplexity, Hybrid — with boundary protection
- **Extra ContextItem fields**: `supersedes`, `embedding`, `parent_id`, `cost`, `latency`, `links`

## Conventions

- **pnpm 10.30.3** (enforced). ESM throughout with `.js` import extensions.
- **TypeScript:** Strict mode, Node16 module resolution
- **Python:** 3.10+, Pydantic models, type hints
- **Formatting:** Prettier (double quotes, semicolons, 2-space, 80 chars)
- **Validation:** Zod schemas (TS), jsonschema (Python), shared JSON Schema files
- **Atomic writes:** FileStore uses write-to-tmp + rename. TS has write queue; Python has threading.Lock.
- **Testing:** Vitest (TS), pytest (Python). Test behavior not implementation.

## Path Aliases

```
@context-engineering/core      → packages/ce-core/src/
@context-engineering/memory    → packages/ce-memory/src/
@context-engineering/providers → packages/ce-providers/src/
@/*           → packages/ce-web-client/src/*
```
