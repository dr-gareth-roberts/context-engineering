# Contributing

Thanks for your interest in contributing to the Context Engineering Toolkit.

## Development Setup

### Prerequisites

- Node.js 18+
- pnpm 10.4.1+ (`corepack enable && corepack prepare pnpm@10.4.1 --activate`)
- Python 3.10+
- Git

### Getting Started

```bash
# Clone the repo
git clone https://github.com/dr-gareth-roberts/context-engineering.git
cd context-engineering

# Install TypeScript dependencies
pnpm install

# Build all packages
pnpm build:all

# Run all TypeScript tests
pnpm test:all

# Set up Python
cd python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run all Python tests
python -m pytest
```

### Verify Everything Works

```bash
# From repo root
pnpm check:all     # TypeScript type checking
pnpm test:all      # TypeScript tests (389 tests)

# From python/
python -m pytest    # Python tests (398 tests)
```

## Project Structure

```
packages/
  ce-core/        Core algorithms (the tight center)
  ce-providers/   OpenAI + Anthropic adapters
  ce-memory/      Memory stores (InMemory, File, SQLite)
  ce-cli/         CLI (11 commands)
python/           Python SDK
schemas/          Shared JSON Schemas
examples/         Usage examples
```

### Package Dependencies

```
ce-cli → ce-core, ce-providers
ce-providers → ce-core
ce-memory → ce-core
```

Changes to `ce-core` may affect all downstream packages. Changes to `ce-memory` are isolated.

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
- Type hints throughout
- Pydantic models for data structures
- ruff for linting (`ruff check`)
- Line length: 100

### Commit Messages

Use imperative mood and be concise:

```
feat: add budget simulation to Python SDK
fix: handle NaN in token estimation
docs: update CLI examples in README
chore: remove tracked build artifacts
```

### Testing

- Test behavior, not implementation
- Use descriptive test names that explain the scenario
- Arrange-Act-Assert pattern
- Mock at boundaries (APIs, file system), not internal code

**TypeScript:**

```bash
cd packages/ce-core && npx vitest run              # All tests in a package
cd packages/ce-core && npx vitest run src/pack.test.ts  # Single file
```

**Python:**

```bash
cd python && python -m pytest                       # All tests
cd python && python -m pytest tests/test_core.py    # Single file
```

### Cross-Language Parity

The TypeScript and Python SDKs share the same core API. If you add or change a core function in one language, consider whether the other needs the same change. Shared JSON Schemas in `schemas/` should stay in sync.

## Pull Requests

1. Create a branch from `main`
2. Make focused, reviewable changes
3. Ensure all tests pass (`pnpm test:all` + `python -m pytest`)
4. Ensure type checking passes (`pnpm check:all`)
5. Write a clear PR description explaining **what** and **why**
6. Link related issues

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
