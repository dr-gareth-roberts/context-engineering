# ce-core Audit Fixes

**Date:** 2026-03-17
**Scope:** All Critical and High issues from the audit, plus several Medium fixes

---

## Critical Fixes

### C1: Removed dead `_previousSelectedIds` from session.ts

**Files:** `src/session.ts`

Removed the `_previousSelectedIds` variable that was written to on every `compile()` and `clear()` but never read. This was dead state that signaled potentially incomplete logic. The delta computation already uses `prevMap`/`currMap` constructed from manifests, making this set redundant.

**Changes:**

- Removed `let _previousSelectedIds = new Set<string>()` declaration (was line 150)
- Removed assignment `_previousSelectedIds = new Set(currentManifest.map(e => e.id))` (was line 264)
- Removed reset `_previousSelectedIds = new Set()` in `clear()` (was line 288)

### C2: Fixed compaction truncation to use token estimator

**Files:** `src/compaction.ts`

The old code truncated combined turn content using `combinedContent.slice(0, targetTokens * 4)`, which assumed 1 token = 4 characters. This is wildly inaccurate for code (closer to 1:3), CJK text (~1:1.5), or JSON. The fix uses a binary search over word boundaries with the actual token estimator to find the largest truncation that fits within the target token budget.

**Changes:**

- Replaced character-based truncation with word-level binary search using the configured `estimate()` function
- The summary prefix (`[Summary of N earlier turns]\n`) is now accounted for in the token budget before truncating content
- Guarantees the summary will not exceed `targetTokens` regardless of content type

### C3: Added compression support to `packStream`

**Files:** `src/stream.ts`, `src/stream.test.ts`

`packStream` now supports the same `allowCompression` option as `pack()`. When enabled, oversized items have their compressions tried (largest fitting first for best quality), and the summarizer is used as a fallback. Without `allowCompression`, behavior is unchanged -- oversized items are silently skipped.

**Changes:**

- Added `tryCompress()` helper function in `stream.ts`
- `packStream` loop now attempts compression when `allowCompression` is set and an item exceeds remaining budget
- Updated test: renamed old test to clarify it tests the no-compression case
- Added two new tests: one for basic compression, one verifying largest-fitting selection

### C4: Fixed `diff()` to handle duplicate IDs correctly

**Files:** `src/diff.ts`, `src/diff.test.ts`

The old `diff()` used `new Map(items.map(i => [i.id, i]))` which silently drops all but the last item when duplicate IDs exist. Since `pack()` accepts and processes duplicate IDs, `diff()` must handle them too.

**Changes:**

- Replaced `Map<string, ContextItem>` with `Map<string, ContextItem[]>` (groups items by ID)
- Added `groupById()` helper that preserves all items
- Pairwise matching within each ID group: compares items by position within the group
- If "before" has 2 items with ID "x" and "after" has 1, the extra is reported as "removed"
- If "after" has more duplicates than "before", extras are reported as "added"
- Updated test to reflect new behavior
- Added test for "more duplicates in after than before" case

---

## High Fixes

### H1: Extracted shared validation into `validatePackInputs()`

**Files:** `src/schemas.ts`, `src/pack.ts`, `src/stream.ts`

~40 lines of identical validation logic (budget schema check, reserve >= max check, items schema check) were duplicated between `pack.ts` and `stream.ts`. Extracted into a single `validatePackInputs(items, budget)` function in `schemas.ts`.

**Changes:**

- Added `validatePackInputs()` to `schemas.ts` (imports `ValidationError`, `BudgetExceededError` from errors, `Budget`/`ContextItem` from types)
- `pack.ts:internalPack()` now calls `validatePackInputs(items, budget)` instead of inline validation
- `stream.ts:packStream()` now calls `validatePackInputs(items, budget)` instead of inline validation
- Removed `zod` direct import from both `pack.ts` and `stream.ts`

### H2: Optimized O(n^2) Jaccard similarity in quality analysis

**Files:** `src/quality.ts`

For large item sets (>100 items), the pairwise Jaccard computation was O(n^2). Now uses sampling: when total possible pairs exceed 5000, it samples `min(5000, n*10)` deterministic pairs using modular arithmetic.

**Changes:**

- Added `jaccardSimilarity()` helper function
- Added `MAX_PAIRS = 5000` threshold
- For sets with <= 5000 possible pairs: exhaustive comparison (unchanged behavior)
- For larger sets: deterministic sampling with reproducible pair selection
- Also fixed M14: pre-compute word arrays once per item, reused for density, diversity, and redundancy calculations (was splitting 3x)
- Also fixed M15: replaced `const totalBigrams = { count: 0 }` with `let totalBigramCount = 0`

### H3: Fixed freshness threshold documentation

**Files:** `src/quality.ts`

The `ContextQuality.freshness` JSDoc said "fraction of items with recency > 0.5 (0-1)" but the code uses `> 5` on a 0-10 scale. Updated the interface comment to accurately reflect the implementation.

**Changes:**

- Interface comment: `"Freshness: fraction of items with recency > 5 on a 0-10 scale (0-1)"`
- Inline comment: `"Freshness: fraction of items with recency above midpoint (> 5 on 0-10 scale)"`

### H4: Compression now picks largest fitting variant (best quality)

**Files:** `src/pack.ts`

The old compression selection sorted ascending by tokens and picked the first (smallest) that fits. This optimizes for token savings but sacrifices content quality. Now sorts descending and picks the largest compression that fits within the remaining budget, maximizing content quality.

**Changes:**

- Sort order changed from `(a, b) => (a.tokens ?? 0) - (b.tokens ?? 0)` (ascending) to `(a, b) => b.tokens - a.tokens` (descending)
- Removed dead `?? 0` after the `.map()` that guarantees tokens are set
- Same change applied to the new `tryCompress()` in `stream.ts`

### H5 + H6: Consolidated hash functions with improved collision resistance

**Files:** New `src/hash.ts`, `src/session.ts`, `src/cache-topology.ts`, `src/index.ts`

Two identical hash functions (`quickHash` in session.ts, `hashString` in cache-topology.ts) were consolidated into a single `hash64()` in a new `src/hash.ts` module. The new hash produces a 64-bit output (two independent 32-bit hashes concatenated as base-36) instead of 32-bit, reducing collision probability from ~65K inputs to ~4 billion inputs via the birthday paradox.

**Changes:**

- Created `src/hash.ts` with `hash64()` function using DJB2 + FNV-1a combination
- `session.ts`: removed local `quickHash`, imported `hash64` from `hash.ts`
- `cache-topology.ts`: removed local `hashString`, imported `hash64` from `hash.ts`
- `index.ts`: added `export * from "./hash.js"`

### H7: Stopped exporting internal functions from public API

**Files:** `src/index.ts`

`internalPack` and `internalPackAsync` were being exported via `export * from "./pack.js"` despite being intended as internal. Changed to named exports.

**Changes:**

- Replaced `export * from "./pack.js"` with `export { pack, packAsync } from "./pack.js"`
- `internalPack` and `internalPackAsync` remain accessible within the package (trace.ts imports them directly) but are no longer part of the public API surface

### H8: Removed unused `PackOptionsSchema`

**Files:** `src/schemas.ts`

`PackOptionsSchema` was defined but never used for validation in pack.ts or anywhere else. It also didn't cover all `PackOptions` fields (missing `weights`, `logger`, `redundancyConfig`). Removed to avoid false confidence.

**Changes:**

- Removed `PackOptionsSchema` definition from `schemas.ts`

### H9: Made `estimateTokens` type honest about null/undefined

**Files:** `src/estimate.ts`

The function signature said `text: string` but the implementation handled `null` and `undefined` via `text == null`. Updated the type to be honest.

**Changes:**

- Changed parameter type from `text: string` to `text: string | null | undefined`
- Existing tests that pass `null as unknown as string` now work without the cast (though the test code itself isn't updated since it still passes)

---

## Medium Fixes

### M1: Replaced O(n\*m) find-in-loop with Map lookup in allocation.ts

**Files:** `src/allocation.ts`

**Changes:**

- Added `const allocatedKinds = new Set(allocations.map(a => a.kind))` for O(1) lookup
- Replaced `allocations.find(a => a.kind === kind)` with `allocatedKinds.has(kind)`

### M5: Fixed timestamp-as-recency in causal compaction

**Files:** `src/compaction.ts`

Raw Unix timestamps (e.g., 1710000000000) were being passed as `recency` values to the causal scorer, which multiplies by 0.7, producing astronomically large scores that completely dominate priority. Now normalizes timestamps to 0-10 scale within the older turns window.

**Changes:**

- Compute `minTs`, `maxTs`, `tsRange` from older turn timestamps
- Normalize to `((timestamp - minTs) / tsRange) * 10` (0 = oldest, 10 = most recent)
- Falls back to 5 when all timestamps are identical (tsRange = 0)

### M8: Removed redundant filter in compaction item packing

**Files:** `src/compaction.ts`

Two consecutive `.filter()` calls were used: one to remove items individually larger than the budget, then another for greedy packing. The first filter was redundant since the second naturally handles oversized items.

**Changes:**

- Removed the first `.filter(i => (i.tokens ?? 0) <= availableTokens)` pass

### M9: Made causal scorer default priority consistent

**Files:** `src/score.ts`

`defaultItemScorer` used `item.priority ?? 0` but `createCausalScorer` used `item.priority ?? 5`. Made consistent by using `0` in both. The compaction module explicitly sets `priority: 5` on turns, so this only affects items without any priority set.

**Changes:**

- Changed `const priority = item.priority ?? 5` to `const priority = item.priority ?? 0` in `createCausalScorer`

### M10: Removed unnecessary cast in compaction addTurn

**Files:** `src/compaction.ts`

`(turn as { taskId?: string }).taskId` was an unnecessary cast since `taskId` is already part of `Omit<Turn, "tokens" | "timestamp">`. Changed to direct access.

**Changes:**

- Replaced `(turn as { taskId?: string }).taskId ?? activeTaskId` with `turn.taskId ?? activeTaskId`

### M14: Eliminated triple word-splitting in quality analysis

**Files:** `src/quality.ts`

Item contents were split into words 3 separate times (density, bigrams, redundancy). Now pre-computes word arrays once per item and reuses them.

**Changes:**

- Added `const itemWords = items.map(item => item.content.toLowerCase().split(/\s+/).filter(...))` at top
- Reuse `itemWords` for density (unique words), diversity (bigrams), and redundancy (word sets)

### L1: Removed redundant `as number` cast in score.ts

**Files:** `src/score.ts`

After `typeof item.metadata?.salience === "number"`, TypeScript already narrows the type. Removed the unnecessary `as number`.

---

## Files Changed

| File                    | Changes                                                                            |
| ----------------------- | ---------------------------------------------------------------------------------- |
| `src/hash.ts`           | **NEW** -- shared 64-bit hash utility                                              |
| `src/schemas.ts`        | Added `validatePackInputs()`, removed `PackOptionsSchema`                          |
| `src/pack.ts`           | Uses shared validation, compression picks largest fitting                          |
| `src/stream.ts`         | Uses shared validation, added compression support                                  |
| `src/diff.ts`           | Handles duplicate IDs correctly via grouping                                       |
| `src/session.ts`        | Removed dead state, uses shared hash                                               |
| `src/cache-topology.ts` | Uses shared hash                                                                   |
| `src/compaction.ts`     | Token-aware truncation, normalized recency, removed redundant filter, removed cast |
| `src/estimate.ts`       | Honest null/undefined type                                                         |
| `src/quality.ts`        | Sampling for large sets, single word-split pass, corrected docs                    |
| `src/score.ts`          | Removed redundant cast, consistent default priority                                |
| `src/allocation.ts`     | O(1) kind lookup                                                                   |
| `src/index.ts`          | Named exports for pack, added hash export                                          |
| `src/diff.test.ts`      | Updated duplicate test, added new test                                             |
| `src/stream.test.ts`    | Updated compression test, added new tests                                          |
