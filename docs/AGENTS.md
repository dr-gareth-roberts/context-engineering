# AGENTS.md

This file helps AI coding agents understand how to work with this project.

## Project Overview

- **Language**: TypeScript + Python
- **Project**: Monorepo with 17 TypeScript packages + dual Python SDK
- **Package Manager**: pnpm
- **Test Framework**: Vitest (TS), pytest (Python)
- **Build Tool**: Vite (frontend), tsc (packages), esbuild (server)

## Package Map

### Core

- `ce-core` — pack, score, diff, place, quality, cost, sessions, pipeline, BEADS handoff
- `ce-providers` — OpenAI + Anthropic adapters, token estimators
- `ce-memory` — memory stores (InMemory, File, SQLite, Redis)
- `ce-cli` — CLI with 11 commands

### Multi-Model & Multi-Agent

- `ce-council` — multi-model deliberation (parallel, debate, stepladder, delphi)
- `ce-entangle` — pub/sub mesh for multi-agent context sharing
- `ce-router` — complexity-based model routing

### Quality & Safety

- `ce-adversarial` — red-team with 6 attack types
- `ce-immune` — failure pattern antibodies
- `ce-debugger` — diagnose bad outputs via context analysis
- `ce-drift` — quality degradation monitoring

### Optimisation

- `ce-compiler` — declarative context programs compiled per target model
- `ce-adaptive` — weight learning from outcome feedback
- `ce-time-travel` — git-like checkpoint/fork/merge for context states

### Integration

- `ce-sdk-interceptors` — drop-in OpenAI/Anthropic wrappers
- `ce-frameworks` — LangChain, LlamaIndex, CrewAI middleware
- `ce-rag` — context-aware RAG with information gain

### Internal (not published)

- `ce-web-client` — React 19 playground UI
- `ce-web-server` — Express dev server

### Python

- `context_engineering` — full parity with all TS packages above
- `context_framework` — tri-provider orchestration and domain runtimes

## Commands

- **Install**: `pnpm install`
- **Dev**: `pnpm dev`
- **Build**: `pnpm build`
- **Test**: `pnpm test` — type-check + build (NOT a test runner)
- **Check**: `pnpm check` — type-check only
- **Package Tests**: `pnpm test:packages` — run Vitest suites (1,264 tests)
- **Test All**: `pnpm test:all` — type-check + build + Vitest
- **Build Packages**: `pnpm build:packages` — tsc per package
- **Build All**: `pnpm build:all` — build everything
- **Lint**: `pnpm lint`
- **Format**: `pnpm format`
- **Python Tests**: `cd python && python -m pytest` (908 tests)

## Testing

- **Vitest** for TypeScript, **pytest** for Python
- Write tests for new features before implementation
- Run tests before committing changes
- Use `describe` and `it` blocks (TS) or `class Test*` (Python)
- Mock at boundaries (APIs, file system), not internal code
- All packages depend on `ce-core` — changes to core may affect everything

## Code Style

**TypeScript:**

- Strict mode, no `any`
- ESM with `.js` import extensions
- Prettier (double quotes, semicolons, 2-space indent, 80 chars)
- Zod for validation

**Python:**

- 3.11+, type hints throughout
- Pydantic models for data structures
- ruff for linting and formatting
- Line length: 100

## Constraints

- Do not modify files outside the project directory
- Ask before making breaking changes
- Prefer editing existing files over creating new ones
- Keep dependencies minimal — all packages depend only on ce-core
- Do not commit sensitive data (API keys, secrets, credentials)
