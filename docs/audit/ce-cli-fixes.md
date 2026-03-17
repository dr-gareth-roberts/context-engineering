# ce-cli Audit Fixes

**Date:** 2026-03-17
**Scope:** All fixes applied to `packages/ce-cli/src/` based on the audit in `ce-cli-audit.md`

---

## Files Modified

- `packages/ce-cli/src/output.ts` -- H2, H3, H4
- `packages/ce-cli/src/lib.ts` -- M1, M2, M4, M3 (comment), L1
- `packages/ce-cli/src/cli.ts` -- C1, C2, H1, H5, M5, M6

---

## Critical Fixes

### C1: Fall-through error handling in diff and lint commands

**Problem:** In both the `diff` and `lint` commands, the catch blocks called `outputError()` for ENOENT errors but then fell through to a second `outputError()` call. Although `outputError` returns `never` (calls `process.exit(1)`), the code was structurally wrong and would double-fire if `outputError` were ever refactored.

**Fix:** Added explicit `return` before every `outputError()` call in catch blocks and guard clauses across all commands. This makes control flow unambiguous regardless of how `outputError` is implemented.

**Files:** `cli.ts` lines 219, 248, 265, 278-283

### C2: Budget command passing undefined text after guard

**Problem:** The `budget` command called `outputError("Provide --text or --file")` when `text` was undefined, but did not `return`. TypeScript could not narrow `text` from `string | undefined` to `string` after the `outputError()` call because function calls don't narrow. The subsequent `runBudget(text, ...)` was called with a potentially `undefined` argument according to the type system.

**Fix:** Changed to `return outputError("Provide --text or --file")`. TypeScript now understands the early exit, and `text` is narrowed to `string` in the subsequent code.

**File:** `cli.ts` line 306

---

## High Priority Fixes

### H1: Missing --json flag on budget and lint commands

**Problem:** Every command except `budget` and `lint` had a `--json` flag. Both commands checked `isJsonMode()` internally but never called `setForceJson(true)`, so the `--json` flag had no effect in a TTY.

**Fix:** Added `.option("--json", "Force JSON output")` and `if (options.json) setForceJson(true)` to both commands.

**Files:** `cli.ts` lines 231, 233 (lint), 297, 299 (budget)

### H2: readStdin has no timeout

**Problem:** When `-i -` was passed but no data was piped (e.g., user runs `ce pack -i -` in a terminal), `readStdin()` would hang indefinitely with no feedback.

**Fix:** Added a 30-second timeout that rejects the promise with a helpful error message explaining the issue and showing correct usage. The timeout is cleared when data arrives or an error occurs.

**File:** `output.ts` lines 75-103

### H3: NO_COLOR environment variable not respected

**Problem:** The CLI supported `--no-color` flag but ignored the `NO_COLOR` environment variable, which is a widely adopted standard (https://no-color.org/).

**Fix:**

1. At module initialization, check `process.env.NO_COLOR !== undefined` and set `noColor = true` if present.
2. In the `color()` function, also check `process.env.NO_COLOR !== undefined` directly as a belt-and-suspenders approach (covers cases where the module-level check ran before the env var was set).

**File:** `output.ts` lines 5-8, 40

### H4: forceJson/noColor mutable global state never reset

**Problem:** `forceJson` and `noColor` were module-level mutable variables that could never be reset. This caused issues for library consumers running multiple operations and for test isolation.

**Fix:** Added `resetOutputState()` function that resets both variables to their defaults (respecting `NO_COLOR` env var). Exported via the barrel `index.ts`.

**File:** `output.ts` lines 18-22

### H5: loadItems silently returns [] for unrecognized JSON shapes

**Problem:** When reading from stdin, if the parsed JSON was not an array and did not have `.items` or `.selected` properties, `loadItems` silently returned `[]`. This swallowed malformed input without any indication of the problem.

**Fix:** Replaced `return []` with `return outputError(...)` that provides a clear message about expected input formats and hints at correct usage.

**File:** `cli.ts` lines 70-73

---

## Medium Priority Fixes

### M1: Schema reloading on every lint call

**Problem:** Every call to `lintFile()` loaded all 10 schema files from disk, parsed them, created a new Ajv instance, registered all schemas, and compiled the validator. For JSONL files with N lines, this meant N \* 10 file reads and N Ajv compilations.

**Fix:** Added module-level schema cache (`cachedSchemas`) and Ajv instance cache (`cachedAjv`). The first `lintFile()` call loads schemas and creates the Ajv instance; subsequent calls reuse both caches. This makes JSONL linting O(1) for schema loading regardless of line count.

**File:** `lib.ts` lines 159-201

### M2: Fragile schema directory lookup with hardcoded walk limit

**Problem:** `findSchemasDir` walked up at most 8 levels from the starting directory. This arbitrary limit could fail for deeply nested working directories.

**Fix:** Changed to walk all the way to the filesystem root using `path.dirname(current) === current` as the natural termination condition. Removed the unnecessary `fsExistsSync` wrapper (L1) and use `existsSync` directly.

**File:** `lib.ts` lines 142-157

### M4: Unsafe CacheAwarePack cast in runCost

**Problem:** `runCost` cast the return value of `packWithCacheTopology()` with `as CacheAwarePack`. Since `packWithCacheTopology` already returns `CacheAwarePack`, the cast was unnecessary and potentially misleading.

**Fix:** Removed the `as CacheAwarePack` cast. Also removed the now-unused `CacheAwarePack` type import.

**File:** `lib.ts` lines 385-391, import at line 34

### M5: Version hardcoded in source

**Problem:** The CLI version was hardcoded as `"0.1.0"` in `cli.ts`, which would drift from `package.json`.

**Fix:** Used `createRequire(import.meta.url)` to read `../package.json` at startup and pass the version dynamically to Commander.

**File:** `cli.ts` lines 3, 31-32, 41

### M6: diff command doesn't support stdin or JSONL

**Problem:** The `diff` command used direct `fs.readFile` + `JSON.parse`, so it did not support JSONL input, stdin via `-`, the `{ items: [...] }` wrapper format, or ContextPack shapes with `selected`/`dropped`.

**Fix:** Refactored to use the shared `loadItems()` helper for both `--before` and `--after` arguments. This gives `diff` the same format flexibility as all other commands. Updated the help text to indicate stdin support. Error handling is now consistent with other commands since `loadItems` handles ENOENT and parse errors internally.

**File:** `cli.ts` lines 200-221

### M3: Clarifying comment on pickup ready-filter

**Problem:** The pickup ready-filter reconstructs BEADS IDs by prepending `ce-` to recovered item IDs. While the logic is correct (verified against `contextItemToBeads` and `beadsToContextItem` in core), the non-obvious ID mapping deserved explanation.

**Fix:** Added a comment explaining the ID mapping convention and why the `ce-` prefix reconstruction is correct.

**File:** `lib.ts` lines 358-360

---

## Low Priority Fixes (included)

### L1: Unnecessary fsExistsSync wrapper

**Problem:** `fsExistsSync` wrapped `existsSync` in a try-catch, but `existsSync` already handles errors internally.

**Fix:** Removed `fsExistsSync` and use `existsSync` directly in `findSchemasDir`.

**File:** `lib.ts` (removed function, updated call site at line 151)

---

## What Was NOT Changed

- **Test files:** No test modifications were needed. All changes are backward-compatible -- the fixes correct behavior without changing the public API surface.
- **package.json:** No changes needed. The version is already correct in package.json; the fix just reads it dynamically now.
- **index.ts:** No changes needed. The barrel re-export automatically picks up the new `resetOutputState` export.

---

## Verification Notes

Without bash access, I was unable to run `tsc --noEmit` or `vitest run` directly. The following manual verification was performed:

1. **Type safety of `createRequire`:** Compatible with `module: "Node16"` in tsconfig.json. `createRequire` is available in Node.js 12.2+ and the package requires `>=18`.

2. **readStdin timeout:** The existing test creates a fake stdin with immediate data + null push, so the 30s timeout will not trigger. The `clearTimeout` calls in both the `end` and `error` handlers prevent timer leaks.

3. **NO_COLOR handling:** The env var check at module load sets `noColor = true`. The `color()` function also checks `process.env.NO_COLOR` directly. The `resetOutputState()` function respects `NO_COLOR` when resetting.

4. **Schema cache:** The `cachedSchemas` and `cachedAjv` variables are initialized to `null` and populated on first use. The `loadSchemas` function early-returns when cached. The `getAjv` function early-returns when cached. Thread safety is not a concern in single-threaded Node.js.

5. **diff refactor:** The `loadItems` function returns `ContextItem[]`, and `runDiff` accepts `ContextPack | ContextItem[]`. The existing test writes JSON arrays, which `loadItemsFromFile` parses correctly.

6. **Version reading:** `createRequire(import.meta.url)` creates a `require` function rooted at the module's directory. `require("../package.json")` resolves to `packages/ce-cli/package.json`, which exists. The `as { version: string }` assertion is safe since package.json always has a `version` field.
