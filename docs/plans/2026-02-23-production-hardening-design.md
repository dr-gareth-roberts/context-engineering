# Production Hardening Design

**Date:** 2026-02-23
**Status:** Approved
**Scope:** Full stack — TypeScript packages + Python SDK + CLI

## Problem

The Context Engineering Toolkit has sound algorithms but ~8% test coverage, zero error handling, no input validation, SQL injection vulnerabilities, and missing DX features. This blocks adoption by production teams.

## Approach

Bottom-up hardening: ce-core → ce-memory → ce-providers → ce-cli → Python SDK. Each layer is tested before the next depends on it.

## Design

### 1. Zod Validation Layer (ce-core)

Add `schemas.ts` with Zod schemas for all public types:

```ts
// ContextItemSchema — validates id (non-empty string), content (string),
// priority/recency/score (optional numbers ≥ 0), compressions (optional array)
// BudgetSchema — maxTokens (positive integer), reserveTokens (optional, ≥ 0, < maxTokens)
// PackOptionsSchema — optional scorer, tokenEstimator, summarizer
```

Integration points:

- `pack()` validates items + budget at entry via Zod parse
- `diff()` validates inputs
- Schemas exported for user-side validation
- Zod errors bubble with descriptive paths: `items[3].id: Required`

### 2. Error Handling

Custom error class hierarchy:

- `ContextEngineeringError` (base, extends Error with `code` field)
- `ValidationError` — Zod parse failures, invalid input
- `BudgetExceededError` — reserve > maxTokens
- `EstimationError` — token estimator failures

Applied in:

- `pack.ts`: wrap token estimation, validate budget constraints
- `diff.ts`: handle null/undefined inputs
- `estimate.ts`: handle empty/null strings (return 0), wrap tiktoken errors
- All file I/O in CLI and memory stores

### 3. Test Coverage (~90% target)

**Vitest snapshot tests** for pack results, trace steps, diff output using fixtures data.

**ce-core:**

- pack: empty items, zero budget, negative budget, reserve > max, all items exceed budget, compression selection, custom scorer/estimator, duplicate IDs, snapshot of pack output
- diff: empty arrays, content changes, token changes, ContextPack inputs, identical packs
- score: default weights, custom weights, missing fields, all-zero scores
- estimate: empty string, whitespace, long text, different estimators
- trace: step recording, decision types, compression traces, snapshot of trace output

**ce-memory:**

- All three stores: CRUD, batch put, TTL expiry, salience filtering, limit/pagination
- FileStore: corruption recovery, empty file
- SqliteStore: table creation, upsert, parameterized queries

**ce-providers:**

- Token estimators: OpenAI (tiktoken), Anthropic (heuristic), edge cases

**ce-cli:**

- All commands with valid/invalid input
- TTY vs pipe output detection
- Help text, error formatting

**Python (mirror TS):**

- Same edge cases for core, memory, CLI
- Framework + segmentation tests

### 4. CLI Hardening

**TTY-aware output:**

- `process.stdout.isTTY` → human-readable with ANSI colors; piped → JSON
- `--json` flag forces JSON, `--no-color` disables colors
- Minimal ANSI helpers (no heavy deps like chalk)

**Better errors:**

- File I/O wrapped with actionable messages
- Zod errors as formatted bullet list
- Exit codes: 0 success, 1 validation, 2 file error, 3 internal

**stdin support:**

- File arg `-` or piped stdin → read from stdin
- Supports: `cat items.json | ce pack -b 4000`

**Help text:**

- `.description()` on all commander commands
- Usage examples in help output

**Python CLI parity:** Same TTY detection, colors, stdin, exit codes.

### 5. DX Improvements

**JSDoc (TS):** All exported functions/types/classes with `@param`, `@returns`, `@throws`, `@example`. Not internal functions.

**Docstrings (Python):** Google-style for all public methods with examples.

**Factory functions + presets:**

```ts
createMemoryStore("sqlite", { path: "db.sqlite" });
createMemoryStore("file", { path: "memory.jsonl" });
createMemoryStore("memory");

presets.openai(); // { estimator: openaiTokenEstimator, provider: new OpenAIProvider() }
presets.anthropic(); // { estimator: anthropicTokenEstimator, provider: new AnthropicProvider() }
```

**Configurable scoring weights (TS, matching Python):**

```ts
type ScoringWeights = {
  priority?: number;
  recency?: number;
  salience?: number;
};
pack(items, budget, { weights: { priority: 1.0, recency: 0.5 } });
```

### 6. Production Features

**Streaming pack:**

```ts
async function* packStream(items, budget, options): AsyncGenerator<ContextItem>
```

Yields items as selected — useful for large item sets.

**Structured logging:**

- Optional `logger` in options (defaults to no-op)
- Interface: `{ debug, info, warn, error }` — compatible with console, pino, winston
- Logs: item selection decisions, compression events, budget usage

**Token estimation cache:**

- LRU cache keyed by content hash
- Configurable max size, disabled by default
- Shared across pack calls via options

**SQLite fixes:**

- Parameterize table name validation (allowlist pattern, not interpolation)
- WAL mode for concurrent reads
- Explicit `.close()` method

## Implementation Order

1. ce-core: Zod schemas + errors + validation + tests + JSDoc + scoring weights
2. ce-memory: store hardening + SQL fix + tests + JSDoc + factory
3. ce-providers: error handling + tests + JSDoc + presets
4. ce-cli: TTY output + stdin + help + error formatting + tests
5. Python SDK: mirror all improvements
6. Production features: streaming, logging, cache
7. Integration: snapshot tests, end-to-end CLI tests

## Success Criteria

- All packages pass `vitest run` with >85% line coverage
- Python passes `pytest` with >85% coverage
- CLI handles all error cases gracefully (no stack traces to users)
- Zero `any` types in public APIs
- All public APIs have JSDoc/docstrings
- `ce pack` works with stdin piping
- SQLite store is safe from injection
