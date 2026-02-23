# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Context Engineering Toolkit monorepo — a docs + demos web app plus production-ready SDKs, CLI, and memory stores for building context-aware agents. Dual TypeScript/Python implementations share JSON schemas for compatibility.

## Commands

```bash
# App development
pnpm dev          # Vite dev server on port 3000 (--host enabled)
pnpm build        # Build frontend (Vite) + bundle server (esbuild) to dist/
pnpm start        # Run production server (NODE_ENV=production)

# Quality
pnpm check        # TypeScript type checking (root: client + server + shared)
pnpm check:all    # Type-check all workspace packages
pnpm format       # Prettier (double quotes, semicolons, 2-space, 80 chars)

# Testing (122 TS tests + 193 Python tests)
pnpm test:all                           # Run all package tests (Vitest)
cd packages/ce-core && npx vitest run   # Single package tests
npx vitest run src/pack.test.ts         # Single test file (from package dir)

# Python SDK
cd python && pip install -e ".[dev]"    # Install for development
cd python && python -m pytest           # Run all Python tests
cd python && python -m pytest tests/test_core.py  # Single test file

# Packages
pnpm build:all    # Build all workspace packages (tsc per package)
```

## Architecture

### Monorepo Layout (PNPM workspaces)

```
client/              React 19 frontend (Vite root). Entry: client/src/main.tsx
server/              Minimal Express server (~30 lines). Static files + SPA fallback
shared/              Constants shared between client and server (COOKIE_NAME, etc.)
packages/ce-core     Core types + algorithms: pack(), diff(), tracePack(), estimateTokens()
packages/ce-memory   Memory stores: InMemoryStore, FileStore (JSONL), SqliteStore
packages/ce-providers  OpenAI + Anthropic adapters, token estimators (tiktoken, heuristic)
packages/ce-cli      CLI (`ce`) — pack, trace, diff, lint, budget commands
python/              Python SDK mirroring TS API + extras (framework, segmentation)
schemas/             JSON Schemas shared by TS + Python (context-item, context-pack, etc.)
```

### Package Dependency Graph

```
ce-cli → ce-core, ce-providers
ce-providers → ce-core
ce-memory → ce-core
client app → ce-core, ce-memory, ce-providers
```

### Core Algorithms (ce-core)

- **pack()**: Greedy score-based context packing within a token budget. Validates inputs via Zod schemas. Default score = `priority * 1.0 + recency * 0.7 + salience * 0.5`. Supports compressions, custom summarizers, configurable weights, structured logging.
- **packStream()**: Async generator version of pack — yields items as selected. Useful for large item sets.
- **tracePack()**: Same as pack but records every decision (include/compress/exclude) with reasons.
- **diff()**: Compares two ContextPacks — returns added, removed, kept, changed items. Validates inputs.
- **estimateTokens()**: Pluggable token counting — default heuristic (words × 1.3), OpenAI (cl100k_base via tiktoken), Anthropic (words × 1.4). Returns 0 for empty/null input.
- **createScorer(weights?)**: Factory for custom scoring functions. Weights: `{ priority, recency, salience }`.
- **createCachedEstimator(estimator, { maxSize })**: LRU cache wrapper for token estimators. Keyed by content hash.

### Key Types

```ts
ContextItem { id, content, kind?, priority?, recency?, tokens?, score?, metadata?, compressions? }
Budget { maxTokens, reserveTokens? }
PackOptions { scorer?, tokenEstimator?, summarizer?, weights?: ScoringWeights, logger?: Logger }
ScoringWeights { priority?: number, recency?: number, salience?: number }
ContextPack { budget, selected[], dropped[], totalTokens, stats? }
MemoryStore { put(), get(), query(), forget() }
LLMProvider { generate(messages, options?) }
Logger { debug, info, warn, error } // compatible with console, pino, winston
```

### Validation & Errors (ce-core)

All public APIs validate inputs via Zod schemas (`ContextItemSchema`, `BudgetSchema`, `PackOptionsSchema`). Errors use a class hierarchy:

- `ContextEngineeringError` — base class with `code` field
- `ValidationError` — Zod parse failures (descriptive paths: `items[3].id: Required`)
- `BudgetExceededError` — reserveTokens >= maxTokens
- `EstimationError` — token estimator failures

### Factories & Presets

```ts
// ce-memory: create any store by type
createMemoryStore("memory")
createMemoryStore("file", { path: "memory.jsonl" })
createMemoryStore("sqlite", { path: "db.sqlite" })

// ce-providers: pre-configured estimator bundles
presets.openai    // { estimator: openaiTokenEstimator }
presets.anthropic // { estimator: anthropicTokenEstimator }
```

### Python SDK Extras (beyond TS parity)

- **AgentContextManager** (`framework.py`): High-level orchestration — adaptive budgeting, segmentation, memory queries, handoff protocol for multi-agent coordination.
- **Segmenters** (`segmentation.py`): StructuralSegmenter (markdown headers), SemanticSegmenter (embeddings), PerplexitySegmenter (LLM-based), HybridSegmenter. All include boundary protection (UUIDs, dates, identifiers).
- Python SDK mirrors TS validation (Pydantic), error handling, CLI TTY-awareness, and Google-style docstrings on all public methods.

### CLI (`ce`)

TTY-aware output: human-readable with ANSI colors when interactive, JSON when piped. Supports `--json` flag to force JSON, `--no-color` to disable colors, and stdin via `-i -` or pipe.

Exit codes: 0 success, 1 validation, 2 file error, 3 internal. Python CLI (`python -m context_engineering`) has feature parity.

### Build Pipeline

Vite builds client → `dist/public`. esbuild bundles `server/index.ts` → `dist/index.js` (ESM, external packages).

### Path Aliases

```
@/*           → client/src/*
@shared/*     → shared/*
@ce/core      → packages/ce-core/src/
@ce/memory    → packages/ce-memory/src/
@ce/providers → packages/ce-providers/src/
@assets       → attached_assets/
```

## Key Conventions

- **Package manager:** pnpm 10.4.1 (enforced via `packageManager` field)
- **TypeScript:** Strict mode, ESNext target, bundler module resolution, all packages ESM
- **Python:** 3.10+, Pydantic models, type hints throughout
- **UI components:** shadcn/ui (new-york style, `components.json`). Add via shadcn CLI
- **Styling:** Tailwind CSS v4 with CSS custom properties. Custom marker colors (marker-blue, marker-red, marker-green, marker-black) for whiteboard aesthetic
- **Animations:** Framer Motion
- **Routing:** Wouter (patched — see `patches/wouter@3.7.1.patch`)

## Environment Variables

Client-side (prefixed `VITE_`):

- `VITE_OAUTH_PORTAL_URL`, `VITE_APP_ID` — OAuth configuration
- `VITE_ANALYTICS_ENDPOINT`, `VITE_ANALYTICS_WEBSITE_ID` — Umami analytics

Server-side:

- `PORT` — Server port (defaults to 3000)
