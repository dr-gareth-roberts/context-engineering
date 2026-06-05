# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with the context-engineering repository.

## Project Overview

The context-engineering toolkit treats the LLM context window as a first-class engineering problem: deciding _what goes into the window_, with scoring, placement, packing, caching, quality gates, adversarial testing, and multi-model orchestration.

The core pipeline is:

```
items + budget → score → place → pack → quality gate → trace
```

The workspace is a **pnpm monorepo of 17 TypeScript library packages** (plus a two-package web inspector) with a **1:1 Python port**, 2,200+ tests across both stacks, and an interactive in-browser inspector.

## Project Structure

```
packages/                 # 17 library packages + the web inspector (client + server)
  ce-core/                # Core algorithms: pack, diff, trace, placement, quality,
                          #   cache-topology, allocation, sessions, pipelines, cost, BEADS handoff
  ce-cli/                 # CLI: packing, placement, quality, cost, agent handoff, linting, budgets
  ce-council/             # Council of Experts — multi-model deliberation / debate strategies
  ce-immune/              # Context Immune System — antibodies against past context failures
  ce-compiler/            # Context Compiler — declarative context programs → optimized layouts
  ce-adaptive/            # Adaptive learning — adjusts scoring weights from output quality
  ce-time-travel/         # Git-like branching/forking/merging of context states
  ce-adversarial/         # Adversarial Context Tester — red-team pipelines with failure injection
  ce-drift/               # Drift Detector — monitors context-quality degradation over time
  ce-entangle/            # Context Entanglement — pub/sub mesh for multi-agent context sharing
  ce-debugger/            # Context Debugger — traces bad outputs back to context problems
  ce-memory/              # Pluggable memory stores (in-memory, JSONL, SQLite)
  ce-providers/           # OpenAI / Anthropic provider adapters + token estimators
  ce-rag/                 # Context-aware RAG — retrieves only chunks that add new information
  ce-router/              # Model Router — routes to the cheapest capable model
  ce-sdk-interceptors/    # Drop-in context-management wrappers for the OpenAI / Anthropic SDKs
  ce-frameworks/          # Middleware for LangChain, LlamaIndex, CrewAI (duck-typed)
  ce-web-client/          # React-based context inspector UI
  ce-web-server/          # Express server for production deployment of the inspector
examples/                 # Runnable demonstrations (rag-chatbot, code-review-council, …)
python/
  context_engineering/    # Python port of the packages above (1:1 parity; the published package)
  context_framework/      # Domain-specific runtime modules built on the toolkit
  tests/                  # pytest suite
docs/                     # Documentation and wiki
scripts/                  # Utility scripts
```

## Development Setup

### Prerequisites

- Node.js **22** (`.nvmrc` pins it; `nvm install && nvm use`). Node ≥ 20 is supported; newer majors may fail the `better-sqlite3` native build.
- pnpm ≥ 10 (repo pins `pnpm@10.30.3` via `packageManager`)
- Python ≥ 3.11

### Installation

```bash
pnpm install                 # JS/TS workspace
pnpm build:all               # build every package + the web app (required before type-checking)

cd python
pip install -e ".[dev]"      # Python port + dev tooling
```

> The TypeScript packages resolve each other through their built `dist/` output, so
> **`pnpm build:all` must run before `pnpm check:all`** on a fresh checkout — otherwise
> tsc reports "Cannot find module '@context-engineering/core'".

## Common Development Commands

### Build

```bash
pnpm build:all        # packages + web app
pnpm build:packages   # packages only
pnpm build:app        # web app only (vite build + esbuild server bundle)
```

### Test

```bash
pnpm test:all         # TypeScript (build + check + app) and then package unit tests
pnpm test:packages    # package unit tests only (Vitest)
pnpm test             # fast app gate: type-check + build:app
cd python && python -m pytest   # Python tests
```

### Code quality

```bash
pnpm check:all        # tsc --noEmit across packages + root
pnpm lint             # ESLint
pnpm lint:fix         # ESLint with --fix
pnpm format           # Prettier write
npx prettier --check .   # Prettier verification (CI gate)

cd python
ruff check .          # lint
ruff format .         # format
pyright               # type-check (CI pins PYRIGHT_PYTHON_FORCE_VERSION)
```

### Development server

```bash
pnpm dev      # context inspector (Vite dev server, default http://localhost:5173)
pnpm start    # production server (serves the built app via Express)
```

### Running examples

```bash
npx tsx examples/rag-chatbot/index.ts
npx tsx examples/code-review-council/index.ts
npx tsx examples/production-agent/index.ts
```

## CI Gates (mirror locally before pushing)

CI (`.github/workflows/ci.yml`) runs four jobs; reproduce them to stay green:

1. **TypeScript** (Node 20 & 22): `pnpm install --frozen-lockfile` → `pnpm build:all` → `pnpm check:all` → `pnpm test:packages` → `pnpm test`
2. **Python** (3.11 & 3.12): `pip install -e ".[dev]"` → `pyright` → `python -m pytest`
3. **Lint & Format**: `npx prettier --check .` → `pnpm lint`
4. **Python lint**: `ruff check .`

## Testing Approach

- **TypeScript**: Vitest; each package owns its suite (`.test.ts` or `__tests__/`).
- **Python**: pytest under `python/tests/`, mirroring the TypeScript suites.
- Examples in `examples/` double as end-to-end demonstrations.

## Key Architectural Concepts

### Core pipeline (`ce-core`)

`items + budget → score → place → pack → quality gate → trace`

1. **Score** — assign relevance/priority/novelty to candidate items
2. **Place** — decide arrangement within the window
3. **Pack** — knapsack-style selection under the token budget
4. **Quality gate** — validate the packed result against thresholds
5. **Trace** — record decisions for debugging and analysis

### Major subsystems

Council (multi-LLM deliberation), Immune System (toxic-context antibodies), Compiler
(declarative specs), Entangle (multi-agent pub/sub), Time Travel (context versioning),
Drift (degradation monitoring), Adversarial (failure injection), Router (cost-aware
model selection), and RAG (novelty-aware retrieval).

## File Conventions

### TypeScript

- Public API exported from `src/index.ts`
- Config: `tsconfig.json`, `vitest.config.ts`
- Tests: `__tests__/` or `.test.ts`; ESLint + Prettier

### Python

- Parity package: `python/context_engineering/` (public API in `__init__.py`)
- Domain runtimes: `python/context_framework/`
- Tests under `python/tests/`; Ruff (lint + format) + Pyright

## Important Files

- `package.json` (root) — workspace scripts
- `pnpm-workspace.yaml` — workspace package globs
- `python/pyproject.toml` — Python package + dev tooling (only `context_engineering*` is published)
- `.github/workflows/` — CI and publish workflows
- `docs/wiki/` — architecture and feature documentation
- `.nvmrc` — pinned Node version

## Recommended Workflow

1. Branch from `main`; implement in the relevant package(s) and keep the Python port in sync.
2. Add/update tests on both stacks.
3. Run the CI gates above locally — **leave nothing failing**.
4. Open a focused pull request.
