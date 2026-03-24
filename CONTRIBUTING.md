# Contributing

Thanks for your interest in contributing to the Context Engineering Toolkit.

## Development Setup

### Prerequisites

- Node.js 18+ (CI tests 18, 20, 22; `.nvmrc` pins to 22 for local dev)
- pnpm 10.30.3+ (`corepack enable && corepack prepare pnpm@10.30.3 --activate`)
- Python 3.11+
- Git

### Getting Started

```bash
git clone https://github.com/dr-gareth-roberts/context-engineering.git
cd context-engineering

# TypeScript
pnpm install
pnpm build:all

# Python
cd python
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Verify Everything Works

```bash
# TypeScript (1,264 tests across 17 packages)
pnpm test:all

# Python (908 tests)
cd python && python -m pytest

# Type checking
pnpm check:all
```

## Project Structure

```
packages/
  ce-core/              Core algorithms (pack, diff, trace, placement, quality, cost, session, pipeline)
  ce-providers/         OpenAI + Anthropic adapters, token estimators, summarizer
  ce-memory/            Memory stores (InMemory, File, SQLite, Redis)
  ce-cli/               CLI (11 commands)
  ce-sdk-interceptors/  Drop-in wrappers for OpenAI/Anthropic SDKs
  ce-adaptive/          Adaptive weight learning from outcome feedback
  ce-frameworks/        Middleware for LangChain, LlamaIndex, CrewAI
  ce-debugger/          Diagnose bad model outputs via context analysis
  ce-rag/               Context-aware RAG with information gain scoring
  ce-router/            Route to cheapest model by context complexity
  ce-council/           Multi-model deliberation (4 debate strategies)
  ce-adversarial/       Red-team context pipelines (6 attack types)
  ce-time-travel/       Git-like checkpoint/fork/merge for context states
  ce-drift/             Context quality degradation monitoring
  ce-immune/            Failure pattern antibodies for context screening
  ce-compiler/          Declarative context programs compiled per model
  ce-entangle/          Multi-agent context sharing via pub/sub mesh
  ce-web-client/        React 19 docs + demos web app
  ce-web-server/        Express server for the web app
python/
  context_engineering/  Python SDK (full API parity with TS + advanced features)
  context_framework/    Tri-provider orchestration and domain runtimes
schemas/                Shared JSON Schemas (cross-language validation)
```

### Package Dependencies

```
ce-cli               → ce-core, ce-providers
ce-providers         → ce-core
ce-memory            → ce-core
ce-sdk-interceptors  → ce-core, ce-providers
ce-adaptive          → ce-core
ce-frameworks        → ce-core
ce-debugger          → ce-core
ce-rag               → ce-core
ce-router            → ce-core
ce-council           → ce-core
ce-adversarial       → ce-core
ce-time-travel       → ce-core
ce-drift             → ce-core
ce-immune            → ce-core
ce-compiler          → ce-core
ce-entangle          → ce-core
```

Changes to `ce-core` may affect all downstream packages. Changes to `ce-memory` are isolated.

### Path Aliases

```
@context-engineering/core      → packages/ce-core/src/
@context-engineering/memory    → packages/ce-memory/src/
@context-engineering/providers → packages/ce-providers/src/
@/*                            → packages/ce-web-client/src/*
```

## Commands Reference

```bash
# Testing
pnpm test:all                           # Type-checks, builds, then runs all Vitest suites
cd packages/ce-core && npx vitest run   # Single package
npx vitest run src/pack.test.ts         # Single file (from package dir)
cd python && python -m pytest           # All Python tests
cd python && python -m pytest tests/test_core.py  # Single file

# Type checking
pnpm check:all    # TypeScript strict mode across all packages

# Building
pnpm build:all    # Build all workspace packages (tsc) + frontend (Vite) + server (esbuild)
pnpm build        # Build frontend (Vite) + bundle server (esbuild)

# Formatting & linting
pnpm format       # Prettier
pnpm lint         # ESLint
cd python && ruff check . && ruff format .
```

## Making Changes

### Branch Naming

- `feature/short-description` — new functionality
- `fix/short-description` — bug fixes
- `chore/short-description` — maintenance, docs, CI

### Code Style

**TypeScript:**

- Strict mode, no `any`
- ESM with `.js` import extensions
- Prettier formatting (double quotes, semicolons, 2-space indent, 80 chars)
- Zod for validation

**Python:**

- 3.11+, type hints throughout
- Pydantic models for data structures
- ruff for linting and formatting
- Line length: 100

### Commit Messages

Use imperative mood:

```
feat: add budget simulation to Python SDK
fix: handle NaN in token estimation
docs: update CLI examples in README
```

### Testing

- Test behaviour, not implementation
- Descriptive test names that explain the scenario
- Arrange-Act-Assert pattern
- Mock at boundaries (APIs, file system), not internal code

### Cross-Language Parity

The TypeScript and Python SDKs share the same core API. If you add or change a core function in one language, consider whether the other needs the same change. Shared JSON Schemas in `schemas/` must stay in sync with both Zod schemas (TS) and Pydantic models (Python).

## Pull Requests

1. Create a branch from `main`
2. Make focused, reviewable changes
3. Ensure all tests pass (`pnpm test:all` + `python -m pytest`)
4. Ensure type checking passes (`pnpm check:all`)
5. Write a clear PR description explaining **what** and **why**

### PR Checklist

- [ ] Tests pass (both TS and Python if applicable)
- [ ] Type checking passes
- [ ] New features have tests
- [ ] Breaking changes are documented
- [ ] Commit messages follow conventions

## Reporting Issues

Use [GitHub Issues](https://github.com/dr-gareth-roberts/context-engineering/issues). Include:

- What you expected vs. what happened
- Minimal reproduction steps
- Environment (Node/Python version, OS)
- Error messages and stack traces

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](./LICENSE).
