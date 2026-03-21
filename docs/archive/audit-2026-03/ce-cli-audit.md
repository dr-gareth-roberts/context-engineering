# ce-cli Deep Audit

**Date:** 2026-03-17
**Auditor:** Claude Opus 4.6
**Scope:** All source files in `packages/ce-cli/src/` (4 source files, 3 test files)
**Files audited:**

- `src/cli.ts` (697 lines) -- CLI entry point, command definitions
- `src/lib.ts` (407 lines) -- Command implementations, schema loading
- `src/output.ts` (72 lines) -- Output formatting, TTY detection, ANSI colors
- `src/index.ts` (2 lines) -- Re-export barrel
- `src/cli.test.ts` (571 lines) -- End-to-end subprocess tests
- `src/lib.test.ts` (367 lines) -- Unit tests for lib functions
- `src/output.test.ts` (70 lines) -- Unit tests for output utilities

---

## Summary

The CLI is well-structured with clean separation between command definitions (`cli.ts`), business logic (`lib.ts`), and output formatting (`output.ts`). The codebase has solid test coverage and consistent patterns. However, there are several bugs, a few design issues with error handling and state management, and some missing validation. The most impactful issues involve a fall-through bug in the `diff` error handler, missing `--json` support on two commands, and mutable global state for output mode that could bite in testing or library usage.

**Issue counts:** 2 Critical, 5 High, 8 Medium, 6 Low, 5 Notes

---

## Critical Issues

### C1. `diff` command error handler falls through after ENOENT (cli.ts:213-219)

**Severity: CRITICAL -- Bug**

The `diff` command's catch block calls `outputError` for ENOENT but then unconditionally calls `outputError` again. Since `outputError` calls `process.exit(1)`, the second call is unreachable for ENOENT errors -- but for _all other errors_, the first branch is skipped and execution falls through correctly. The real bug is that `outputError` returns `never`, but the code reads as if it intends the ENOENT branch to be an early return with a more specific message, yet any non-ENOENT error also reaches the second `outputError` correctly. The structural issue is the _missing `return`_ after the ENOENT `outputError` call, which makes the code confusing and fragile if `outputError` were ever changed to not exit:

```typescript
} catch (err) {
  const msg = err instanceof Error ? err.message : String(err);
  if (msg.includes("ENOENT")) {
    outputError("File not found", "Check --before and --after paths");
    // Falls through -- but outputError calls process.exit(1) so this is dead code
  }
  outputError(msg);  // This would double-fire if outputError didn't exit
}
```

This same pattern appears in the `lint` command (lines 273-276), which has the identical fall-through after the ENOENT check. Both should use `return` or `else`:

```typescript
if (msg.includes("ENOENT")) {
  return outputError("File not found", "Check --before and --after paths");
}
outputError(msg);
```

Currently "works" because `outputError` is typed as `never` and calls `process.exit(1)`, but is a latent bug waiting to surface if the error handling is ever refactored (e.g., to throw instead of exit for testability).

### C2. `budget` command reaches unreachable code after `outputError` (cli.ts:296-302)

**Severity: CRITICAL -- Bug (type unsoundness)**

When `text` is `undefined` (neither `--text` nor `--file` provided), `outputError` is called at line 297, which has return type `never`. However, TypeScript narrowing does not refine `text` after the `outputError` call because it's a function call, not a `throw` or `return`. The subsequent `runBudget(text, ...)` call at line 299 is called with `text` still typed as `string | undefined`:

```typescript
let text = options.text as string | undefined;
if (!text && options.file) {
  text = await fs.readFile(options.file, "utf-8");
}
if (!text) {
  outputError("Provide --text or --file");
  // outputError returns `never`, so this is dead code
  // BUT TypeScript doesn't narrow `text` in the scope below
}
const tokens = runBudget(text, {  // text is still string | undefined here
```

At runtime this works because `outputError` calls `process.exit(1)`. But `runBudget` expects `string`, and `text` could be `undefined` according to the types. The fix: `return outputError(...)` to make TypeScript understand the control flow, or restructure as an `else` block.

---

## High Priority

### H1. `--json` flag missing on `budget` and `lint` commands (cli.ts)

**Severity: HIGH -- CLI UX inconsistency**

Every command except `budget` (line 280) and `lint` (line 222) has a `--json` flag. Both commands _do_ check `isJsonMode()` internally (budget at line 303, lint at lines 251 and 267), but since they don't call `setForceJson(true)`, the `--json` flag has no effect when the user is running in a TTY. Users must pipe output to get JSON from these commands, which is inconsistent with the rest of the CLI.

The `lint` command is particularly affected because it uses `outputError` for validation failures, which outputs JSON only when `isJsonMode()` is true. In TTY mode with `--json`, lint failures would still show human-readable errors.

### H2. `readStdin` has no timeout -- hangs forever if stdin never closes (output.ts:64-72)

**Severity: HIGH -- UX / Reliability**

When `-i -` is passed but no data is piped (e.g., user accidentally runs `ce pack -i -` in a terminal), `readStdin()` will hang indefinitely waiting for `end` event. There is no timeout, no indication to the user that stdin is expected, and no way to abort gracefully.

```typescript
export async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf-8");
    process.stdin.on("data", (chunk: string) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
    // No timeout -- hangs forever if stdin never closes
  });
}
```

Should add a timeout (e.g., 30 seconds) and/or check `process.stdin.isTTY` and warn/error immediately if the user appears to be interactively typing rather than piping.

### H3. `NO_COLOR` environment variable is not respected (output.ts)

**Severity: HIGH -- Standards violation**

The CLI supports `--no-color` flag (cli.ts:38) but does not respect the `NO_COLOR` environment variable, which is a [widely adopted standard](https://no-color.org/). The test harness sets `NO_COLOR=1` (cli.test.ts:32), but the output module ignores it entirely. The `isTTY` check at line 1 handles non-TTY contexts, but `NO_COLOR=1` in a TTY should also disable colors.

```typescript
const isTTY = process.stdout.isTTY ?? false;
// Should also check: process.env.NO_COLOR !== undefined
```

### H4. `forceJson` is mutable global state, never reset (output.ts:2,5-7)

**Severity: HIGH -- Design**

`forceJson` and `noColor` are module-level mutable variables. Once `setForceJson(true)` is called, it stays true for the process lifetime. This is fine for a CLI that runs one command and exits, but:

1. The functions are exported via `index.ts` for library use, where callers may run multiple operations.
2. Tests share module state, so test order can affect results.
3. If commander ever calls multiple subcommand actions (unlikely but possible with chained commands), the state leaks.

### H5. `loadItems` in `cli.ts` returns empty array silently for unrecognized JSON shapes (cli.ts:66)

**Severity: HIGH -- Silent failure**

When reading from stdin, if the parsed JSON is neither an array, nor has `.items`, nor has `.selected`, the function returns `[]`:

```typescript
if (Array.isArray(parsed)) return parsed;
if (Array.isArray(parsed.items)) return parsed.items;
if (Array.isArray(parsed.selected)) {
  return [...parsed.selected, ...(parsed.dropped ?? [])];
}
return []; // Silent empty result for any other shape
```

This silently swallows malformed input. Compare with `loadItemsFromFile` in lib.ts:90 which correctly throws `"Invalid items file: expected array, { items: [] }, or a ContextPack"`. The stdin path should throw the same error.

---

## Medium Priority

### M1. `lintFile` reloads and recompiles all schemas on every invocation (lib.ts:183-229)

**Severity: MEDIUM -- Inefficiency**

Every call to `lintFile` calls `loadSchemas()` which reads all 10 schema files from disk, parses them, creates a new Ajv instance, registers all schemas, and compiles the validator. For JSONL files, this happens for _each line_ individually (cli.ts:243). If a JSONL has 1000 lines, that's 1000 disk reads x 10 files = 10,000 file reads and 1000 Ajv compilations.

The schema cache should be loaded once and reused:

```typescript
// Current: in lint command, per-line
for (const [index, line] of lines.entries()) {
  const data = JSON.parse(line);
  const result = await lintFile(options.schema, data);  // reloads schemas every time
```

### M2. `findSchemasDir` is fragile with hardcoded walk limit (lib.ts:143-153)

**Severity: MEDIUM -- Robustness**

The schema directory finder walks up at most 8 levels from either `cwd()` or the module's directory. The magic number 8 is arbitrary and undocumented. For deeply nested working directories or unusual project structures, this could fail silently and fall through to an error. The search starts from `process.cwd()`, which may be completely unrelated to the package location (e.g., if the CLI is installed globally).

### M3. `runPickup` ready-filter uses string prefix matching that may be fragile (lib.ts:349)

**Severity: MEDIUM -- Potential bug**

The ready filter compares issue IDs with the `ce-` prefix:

```typescript
result.items.filter(item => ready.some(issue => issue.id === `ce-${item.id}`));
```

This assumes the ID mapping `contextItem.id -> "ce-" + contextItem.id` is consistent with how `createHandoff` generates BEADS IDs. If the ID generation in `contextItemToBeads` uses a different prefix or format, items will never match the ready filter, silently returning an empty result.

### M4. `runCost` casts pack result to `CacheAwarePack` unsafely (lib.ts:376)

**Severity: MEDIUM -- Type safety**

```typescript
const packed = packWithCacheTopology(
  items,
  { maxTokens: budget },
  { tokenEstimator: resolveTokenEstimator(options.provider) }
) as CacheAwarePack;
```

The `as CacheAwarePack` cast bypasses type checking. If `packWithCacheTopology` already returns `CacheAwarePack`, the cast is unnecessary. If it returns `ContextPack`, the cast is unsafe and could lead to runtime errors when accessing `cacheableTokens` or `volatileTokens`.

### M5. Version hardcoded in source instead of read from package.json (cli.ts:37)

**Severity: MEDIUM -- Maintenance**

```typescript
.version("0.1.0")
```

This will drift from `package.json` version as the project evolves. Should read from `package.json` dynamically or use a build step to inject it.

### M6. `diff` command doesn't support stdin or the `loadItems` helper (cli.ts:201-205)

**Severity: MEDIUM -- Feature gap / Inconsistency**

All other commands that take items use `loadItems()` which supports stdin (`-`), JSONL, and various JSON shapes. The `diff` command directly reads files with `fs.readFile` and `JSON.parse`, so it:

- Does not support JSONL input
- Does not support stdin for either argument
- Does not support `{ items: [...] }` wrapper format
- Does not support `ContextPack` shape with `selected`/`dropped`

### M7. `lint` command does not have `--json` flag but uses `isJsonMode()` (cli.ts:222-278)

**Severity: MEDIUM -- Inconsistency**

The `lint` command checks `isJsonMode()` at lines 251 and 267 to decide output format, but has no `--json` flag and never calls `setForceJson(true)`. The only way to get JSON output from `lint` is to run it in a non-TTY context (piped). See also H1.

### M8. `budget` command has no `--json` flag but uses `isJsonMode()` (cli.ts:280-313)

**Severity: MEDIUM -- Inconsistency**

Same issue as M7 for the `budget` command. It checks `isJsonMode()` at line 303 but has no `--json` flag. See also H1.

---

## Low Priority

### L1. `existsSync` wrapper is unnecessary (lib.ts:155-161)

**Severity: LOW -- Dead complexity**

`fsExistsSync` wraps `existsSync` in a try-catch, but `existsSync` from Node.js `fs` already handles errors internally and returns `false` if the path doesn't exist. The wrapper adds no value:

```typescript
function fsExistsSync(target: string): boolean {
  try {
    return existsSync(target);
  } catch {
    return false;
  }
}
```

### L2. `colorMetric` function is defined at module level but only used by `quality` command (cli.ts:686-691)

**Severity: LOW -- Code organization**

Not really dead code, but it's the only helper function placed outside the command chain at the bottom of the file. Could be co-located near the quality command for clarity.

### L3. Unused import: `ContextItem` type in cli.ts (cli.ts:4)

**Severity: LOW -- Dead import**

`ContextItem` is imported as a type in cli.ts line 4 but is only used indirectly through the `loadItems` function return type. The import could be removed since TypeScript infers the type from `loadItems`.

Actually, reviewing more carefully: `loadItems` returns `Promise<ContextItem[]>` and the import is used in the function signature. This is used and valid. **Retracted.**

### L3 (revised). Inconsistent error message phrasing across commands

**Severity: LOW -- UX**

Error messages use different patterns:

- `"File not found: ${input}"` (pack, lint)
- `"File not found"` with details `"Check --before and --after paths"` (diff)
- `"Provide --text or --file"` (budget)
- `"Input file is empty"` (lint)

### L4. Schema name validation happens at runtime, not at parse time (cli.ts:225-228)

**Severity: LOW -- UX**

The `--schema` option in the `lint` command accepts any string. Invalid schema names only fail deep inside `lintFile` when `schemas[schemaName]` is undefined. Commander could validate choices at parse time:

```typescript
.requiredOption("-s, --schema <name>", "Schema name", { choices: [...] })
```

or the description string could be shorter with a `.choices()` call.

### L5. `parsePositiveInt` error message doesn't mention which command failed (cli.ts:48-54)

**Severity: LOW -- UX**

The error says `"budget must be a positive integer, got: abc"` but doesn't say which command was being run. Since multiple commands use budgets, this could be confusing in scripts.

### L6. Test cleanup is inconsistent (cli.test.ts)

**Severity: LOW -- Test hygiene**

Some tests clean up temp files in `finally` blocks (diff, lint, handoff, pickup), but `lib.test.ts` creates a temp directory at line 109 with `ce-cli-tests-${Date.now()}` and never cleans it up after all tests complete. Should use `afterAll` or `afterEach`.

---

## Notes & Questions

### N1. Commander `--no-color` negation semantics

Commander's `--no-X` pattern sets `opts().X` to `false` (not `opts().noColor` to `true`). The code correctly checks `opts.color === false` at line 45. This is correct but non-obvious behavior that could confuse contributors. Worth a comment.

### N2. `preAction` hook only handles `--no-color`, not `--json`

The `--json` flag must be handled per-command because it's defined on subcommands, not on the program. This means `setForceJson` is called redundantly in every command action. An alternative design would be to define `--json` on the program and handle it in `preAction` alongside `--no-color`.

### N3. The `cost` command's `--model` flag conflicts with the `place` command's `--model` flag

Both use `-m, --model` but with completely different semantics:

- `cost -m`: Pricing model (`claude-sonnet-4-6`, `gpt-4o`, etc.)
- `place -m`: Attention profile model family (`claude`, `gpt4`, `default`)

This could confuse users who use both commands.

### N4. `CacheAwarePack` type in `runCost` (lib.ts)

The `packWithCacheTopology` function is called and its result cast to `CacheAwarePack`. Worth verifying that the return type of `packWithCacheTopology` actually is `CacheAwarePack` (it is, from the core source at `cache-topology.ts:154`), making the cast redundant but harmless.

### N5. Security: file path inputs are not sanitized

The CLI reads arbitrary file paths from `--input`, `--before`, `--after`, `--file`, and `--output`. While path traversal is expected behavior for a CLI tool (users control their own filesystem), the `--output` option in the `handoff` command writes to an arbitrary path. No symlink checks or permission validation are performed. This is standard CLI behavior but worth noting for context.

---

## Good Patterns

1. **Clean separation of concerns:** `cli.ts` handles argument parsing and output formatting, `lib.ts` handles business logic, `output.ts` handles output mode detection and ANSI formatting. Each module has a clear responsibility.

2. **TTY-aware output:** The automatic JSON-vs-human-readable switching based on `process.stdout.isTTY` is a solid CLI UX pattern. Piped output always gets machine-parseable JSON.

3. **`outputError` returns `never`:** The type signature correctly communicates that this function never returns normally. This helps TypeScript catch unreachable code.

4. **Environment variable defaults:** `CE_BUDGET` and `CE_PROVIDER` provide CI/CD ergonomics. Commands don't require explicit flags when env vars are set.

5. **Comprehensive test coverage:** Both unit tests (`lib.test.ts`) and integration tests (`cli.test.ts`) cover all 11 commands. Edge cases like empty input, invalid data, and unknown models are tested.

6. **Consistent `try/catch` pattern:** All async command actions wrap their bodies in try/catch with `outputError` for consistent error reporting.

7. **JSONL support:** The file loader handles both JSON and JSONL formats, and the stdin loader handles multiple JSON shapes (array, `{ items }`, `{ selected, dropped }`).

8. **Webhook reporter is fire-and-forget:** The reporter pattern doesn't block command execution on webhook failures, which is appropriate for telemetry.

9. **Schema validation with Ajv:** Using JSON Schema for validation of external data gives the CLI a formal contract. The schema files are shared with the Python SDK.

10. **The `prebuild` script** copies schemas from the monorepo root into the package, ensuring the published package is self-contained.

---

## File-by-File Detail

### `src/cli.ts` (697 lines)

The main CLI entry point. Defines the `ce` program with 11 subcommands using Commander.

**Line 37:** Version hardcoded as `"0.1.0"` -- should sync with package.json. (M5)

**Lines 38-46:** Global options (`--no-color`, webhook URLs) with `preAction` hook. The hook correctly uses `opts.color === false` for Commander's negation pattern. (N1)

**Lines 48-54:** `parsePositiveInt` -- solid validation, correctly rejects NaN, non-finite, zero, negative, and fractional values. Returns `never` via `outputError` on failure. (L5: could mention command name)

**Lines 56-79:** `loadItems` function.

- Line 66: Returns `[]` for unrecognized JSON shapes from stdin. This silently drops bad input. (H5)
- Lines 69-78: Good ENOENT-specific error messaging.

**Lines 85-137:** `pack` command. Clean implementation. Webhook reporter is created but only fires if URLs are configured. `parsePositiveInt` on budget string could exit mid-action.

**Lines 139-191:** `trace` command. Nearly identical structure to `pack`. DRY opportunity exists but the commands are different enough that duplication is acceptable.

**Lines 193-220:** `diff` command.

- Lines 213-219: Fall-through bug after ENOENT `outputError`. (C1)
- Lines 201-205: Reads files directly without `loadItems`, missing stdin/JSONL support. (M6)

**Lines 222-278:** `lint` command.

- No `--json` flag defined. (H1, M7)
- Lines 239-256: JSONL linting calls `lintFile` per line, reloading schemas each time. (M1)
- Lines 273-276: Same fall-through pattern as diff. (C1)
- Line 236: `outputError` called for empty file but no `return` statement. Same pattern as C2 -- works because `outputError` returns `never`, but control flow is unclear.

**Lines 280-313:** `budget` command.

- No `--json` flag defined. (H1, M8)
- Lines 296-299: `text` is `string | undefined` after `outputError` call. (C2)

**Lines 315-368:** `place` command. Clean. `-s` flag for strategy and `-m` for model are well-defined. Note `-m` means something different here than in `cost`. (N3)

**Lines 370-415:** `quality` command. Uses `colorMetric` helper for human-readable output. Line 406 shows `1 - quality.redundancy` as the "good" version of redundancy -- reasonable UX.

**Lines 417-444:** `effective-budget` command. Simple synchronous action (no `async`). Uses `-t` for tokens, which is the same short flag as `--text` in `budget` command. This is fine since they're different subcommands.

**Lines 446-525:** `handoff` command. Complex but well-structured.

- Lines 492-494: Writes JSONL with trailing newline. Good.
- Lines 496-521: Three output modes (JSON stats when outputting to file, JSON full when no file, JSONL to stdout in human mode). Reasonable but somewhat complex behavior.

**Lines 527-577:** `pickup` command. Supports stdin via `-i -`. Clean implementation.

**Lines 579-683:** `cost` command. Most complex output formatting with nested sections for estimate, projection, and monthly. Well-done human-readable display.

**Lines 686-691:** `colorMetric` helper. Could be in output.ts or co-located with quality command. (L2)

**Lines 693-696:** Top-level `parseAsync` with catch handler. This catches commander parse errors (unknown commands, missing required options). Good.

### `src/lib.ts` (407 lines)

Business logic layer. All `run*` functions are pure-ish wrappers around core functions.

**Lines 1-8:** Ajv import workaround for CJS/ESM interop. Well-documented with comment.

**Lines 9-43:** Imports from core and providers. Clean separation. Types are imported separately from values.

**Lines 45-68:** Schema name type and file mapping. Complete -- covers all 10 schemas.

**Lines 70-93:** `loadItemsFromFile`. Handles JSON arrays, `{ items }`, `{ selected, dropped }`, JSONL, and empty files. Line 90 throws for unrecognized shapes (unlike the stdin path in cli.ts). (H5 contrast)

**Lines 95-101:** `resolveTokenEstimator`. Returns `undefined` for unknown providers, which falls through to the default heuristic estimator in core. This means `CE_PROVIDER=typo` silently uses the heuristic estimator. Could validate the provider string.

**Lines 103-125:** `runPack` and `runTrace`. Thin wrappers. Clean.

**Lines 127-141:** `runDiff` and `runBudget`. `runDiff` accepts `ContextPack | ContextItem[]` which matches the core API. Good.

**Lines 143-161:** `findSchemasDir` and `fsExistsSync`.

- Magic number 8 for walk limit. (M2)
- `fsExistsSync` wrapper is unnecessary. (L1)

**Lines 163-229:** `loadSchemas` and `lintFile`.

- `loadSchemas` reads all 10 files in parallel. Good.
- `lintFile` creates a new Ajv instance every call. (M1)
- Lines 200-225: Array handling for item-level schemas. Smart -- validates each element individually when the schema expects an object. Returns per-item errors with `[i]` path prefixes.

**Lines 233-258:** `runPlace`. Packs first, then places. Returns a custom result type (not a core type). Clean.

**Lines 262-275:** `runQuality`. Packs first, then analyzes selected items only. Reasonable -- quality of what you're actually sending.

**Lines 279-291:** `runEffectiveBudget`. The `ratio` is rounded to 2 decimal places via `Math.round(...*100)/100`. Clean.

**Lines 295-333:** `runHandoff`. Supports both normal pack and cache-topology pack. Options mapping is clean.

**Lines 337-355:** `runPickup`. The ready filter logic at line 349 uses `ce-` prefix assumption. (M3)

**Lines 359-389:** `runCost`. The `as CacheAwarePack` cast at line 376. (M4)

**Lines 393-407:** `createReporterFromCliOptions`. Maps CLI option names to webhook reporter config. Clean.

### `src/output.ts` (72 lines)

Minimal output module. Well-focused.

**Line 1:** `isTTY` is captured once at module load. This is correct for a CLI but means the value can't be mocked in tests without module reload.

**Lines 2-3:** `forceJson` and `noColor` are mutable globals. (H4)

**Lines 13-15:** `isJsonMode` returns `forceJson || !isTTY`. Clean logic but doesn't respect `NO_COLOR` env var. (H3 -- though `NO_COLOR` is about color, not JSON mode)

**Lines 17-31:** ANSI codes defined inline. Lightweight, no dependency on chalk/kleur. Good choice for a CLI with simple color needs.

**Lines 28-31:** `color` function checks `noColor || !isTTY`. Note: when `--no-color` is used in a TTY, this correctly disables colors. But `NO_COLOR=1` in env is ignored. (H3)

**Lines 33-44:** `fmt` object with color helpers. `success`, `error`, `warn` include unicode symbols. Nice.

**Lines 46-52:** `outputResult` switches on `isJsonMode`. Clean.

**Lines 54-62:** `outputError` calls `process.exit(1)`. This makes the function untestable in unit tests without mocking `process.exit`. The type `never` is correct.

**Lines 64-72:** `readStdin` with no timeout. (H2)

### `src/index.ts` (2 lines)

Barrel re-export. Re-exports everything from `lib.js` and `output.js`. This means library consumers get the internal `setForceJson`, `setNoColor`, `readStdin` etc. as public API. May want to be more selective.

### `src/cli.test.ts` (571 lines)

End-to-end tests that run the compiled CLI as a subprocess.

**Line 13:** Uses `import.meta.dirname` which requires Node.js 21.2+. The package.json says `engines: { node: ">=18" }`. This could fail on Node 18-20. However, since this is a test file (not compiled/distributed), it only matters for contributors running tests.

**Line 32:** Sets `NO_COLOR=1` in test env, but the CLI doesn't actually respect this env var. Tests pass because the subprocess is non-TTY (piped stdout), so colors are disabled by the `!isTTY` check. (H3)

**Line 33:** `cwd` is set to `path.resolve(FIXTURES, "..")` which is the project root. This ensures `findSchemasDir` can find the schemas directory.

**Line 40:** `(error as any).code ?? 1` -- the `as any` is needed because Node's `ExecException` type doesn't always include `.code` as a number. Acceptable pragmatism.

**Lines 53-112:** `pack` tests cover file input, stdin array, stdin ContextPack, and missing file. Good coverage.

**Lines 116-131:** `trace` test only checks for `steps` array existence. Could verify step structure.

**Lines 135-166:** `diff` test creates temp files and cleans up in `finally`. Good.

**Lines 170-181:** `budget` tests are minimal but cover the key cases.

**Lines 185-297:** `lint` tests cover valid items, invalid data, and multiple schema types. Good coverage.

**Lines 301-332:** `place` tests cover both strategies. Good.

**Lines 336-353:** `quality` test verifies metric fields. Good.

**Lines 357-391:** `effective-budget` tests cover default model, specific model, and negative input rejection. Good.

**Lines 395-489:** `handoff` and `pickup` tests verify round-trip behavior. The pickup test at line 466 first creates a handoff, extracts the JSONL, writes it to a temp file, and picks it up. Good integration coverage.

**Lines 494-543:** `cost` tests cover model pricing, projections, and unknown model rejection. Good.

**Lines 547-571:** Input validation tests cover non-integer, zero, and negative budgets, plus `--help` output. Good.

### `src/lib.test.ts` (367 lines)

Unit tests for lib functions.

**Line 109:** Temp directory created with timestamp but never cleaned up. (L6)

**Lines 25-51:** `runPack` tests cover budget constraints, empty input, and provider options. Good.

**Lines 79-89:** `runTrace` tests are minimal -- just checks steps exist and createdAt is present.

**Lines 91-106:** `lintFile` tests cover valid, invalid, and unknown schema. Good.

**Lines 108-147:** `loadItemsFromFile` tests cover JSON array, wrapped object, JSONL, empty file, and nonexistent file. Good coverage.

**Lines 186-211:** `runPlace` tests cover strategies, budget constraints, and model parameter.

**Lines 213-247:** `runQuality` tests include a redundancy detection test with identical content. Good.

**Lines 249-270:** `runEffectiveBudget` tests verify specific numbers (140000 for claude at 200000, 83200 for gpt4 at 128000). Good for regression.

**Lines 272-296:** `runHandoff` tests verify issue counts, deferred items, agent identity, and cache topology. Good.

**Lines 298-320:** `runPickup` tests verify round-trip recovery and deferred items. Line 316 checks ID preservation. Good.

**Lines 322-367:** `runCost` tests verify cost fields, projections, monthly estimates, and unknown model error. Good.

### `src/output.test.ts` (70 lines)

Minimal tests for output utilities.

**Lines 4-19:** `fmt` tests only verify that the text is contained in the output. Don't test ANSI codes or color behavior. Acceptable given the simplicity.

**Lines 22-28:** `isTTY` test just checks it returns a boolean. Weak.

**Lines 30-61:** `readStdin` test replaces `process.stdin` with a fake Readable. Good technique but fragile -- relies on `configurable: true` for the property descriptor.

**Lines 63-70:** `outputError` test only tests `fmt.error` formatting, not the actual `outputError` function (which calls `process.exit`). Reasonable -- `process.exit` is hard to test without mocking.

---

## Testing Gaps

1. **No test for `readStdin` timeout behavior** -- because there is no timeout (H2).
2. **No test for `--no-color` flag** -- no e2e test verifies that `--no-color` strips ANSI codes.
3. **No test for empty stdin** -- `ce pack -i -` with empty stdin input.
4. **No test for invalid JSON on stdin** -- `ce pack -i -` with non-JSON input.
5. **No test for `loadItems` returning `[]` on unrecognized shapes** from stdin (H5).
6. **No test for `resolveTokenEstimator` with invalid provider** -- e.g., `--provider typo`.
7. **No test for JSONL lint with many lines** to verify performance (M1).
8. **No test for `findSchemasDir` failure** -- when schemas can't be found.
9. **No test for webhook reporter integration** in CLI context.
10. **No test for `--output` option in handoff** writing actual file content.
