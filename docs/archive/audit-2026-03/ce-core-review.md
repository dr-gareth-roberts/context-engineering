# ce-core Audit Fix Review

**Date:** 2026-03-17
**Reviewer:** Claude Opus 4.6 (1M context)
**Scope:** Verification of 21 fixes across 15 files in `packages/ce-core/src/`

---

## Summary

All 21 claimed fixes have been applied. 19 are correct and complete. 2 have minor issues noted below (one edge case in the binary search, one concern about the quality sampling producing the prefix `[Summary of N earlier turns]\n` with empty content). No new bugs were introduced. Test coverage is adequate for all Critical and High fixes.

**Tests:** Unable to run `npx vitest run` due to Bash permission restrictions during this review. Tests were reviewed statically. The user should verify by running `cd packages/ce-core && npx vitest run`.

---

## Critical Issues

### C1: Dead `_previousSelectedIds` removed from session.ts -- VERIFIED

**Status:** Fixed correctly.

The variable declaration, both assignment sites, and the reset in `clear()` have all been removed. The session module now has no dead state. The delta computation continues to work via `prevMap`/`currMap` constructed from manifests on each compile, which is the correct approach.

Session tests cover: first compile (null delta), subsequent compiles (delta computation), added/removed/changed detection, reuse ratio, prefix reusability, multi-round deltas, clear/reset.

### C2: Compaction truncation uses token estimator via binary search -- VERIFIED

**Status:** Fixed correctly with one minor edge case.

The old `combinedContent.slice(0, targetTokens * 4)` heuristic has been replaced with a proper binary search over word boundaries (compaction.ts lines 217-232). The algorithm:

1. Splits combined turn content into words
2. Computes `contentBudget = max(0, targetTokens - prefixTokens)` (accounts for prefix tokens)
3. Binary searches for the largest word count whose joined text fits within `contentBudget`
4. Uses the configured `estimate()` function for actual token measurement

The binary search uses `Math.ceil((lo + hi) / 2)` which correctly biases toward the upper half, preventing infinite loops when `lo + 1 == hi`. Verified edge cases:

- Single word that fits: correctly includes it
- Single word that doesn't fit: produces empty truncation
- `contentBudget = 0`: produces empty truncation (just the prefix)

**Minor edge case:** When `contentBudget = 0` (prefix alone exceeds the 30% target budget), the summary becomes just `[Summary of N earlier turns]\n` with no actual content. This is technically correct but produces a useless summary that still consumes tokens. The fix is acceptable since this only happens when `prefixTokens >= targetTokens`, which means the budget is very tight.

Tests in `compaction.test.ts` cover the summarization path (lines 62-88) and verify the summary contains the expected prefix. The `causal-compaction.test.ts` tests verify the causal scoring path works end-to-end.

### C3: `packStream` now supports compression -- VERIFIED

**Status:** Fixed correctly.

A `tryCompress()` helper was added to `stream.ts` (lines 83-127) that mirrors the behavior of `applyCompression()` in `pack.ts`:

1. Resolves token counts for all compressions
2. Sorts descending (largest first for best quality) -- matches H4 fix
3. Picks the largest compression that fits
4. Falls back to summarizer if no compression fits
5. Returns null if nothing fits

The main `packStream` loop (lines 61-76) now attempts compression when `allowCompression` is set and an item exceeds the remaining budget, matching `pack()` behavior.

**Behavioral parity with pack():** Both functions now:

- Sort compressions descending by tokens
- Pick largest fitting compression
- Fall back to summarizer
- Set `metadata.compressionNote`

One minor difference: `pack.ts:applyCompression` returns `{ item, usedCompression }` while `stream.ts:tryCompress` returns `ContextItem | null`. This is fine since `packStream` doesn't need the `usedCompression` flag (no trace support).

Tests added:

- `stream.test.ts:68-89`: Basic compression in packStream
- `stream.test.ts:91-117`: Picks largest fitting compression
- `stream.test.ts:50-66`: Renamed to clarify it tests the no-compression case

### C4: `diff()` handles duplicate IDs via group-based matching -- VERIFIED

**Status:** Fixed correctly.

The implementation replaces `Map<string, ContextItem>` with `Map<string, ContextItem[]>` via a `groupById()` helper (diff.ts lines 13-24). The matching logic (lines 67-103):

1. Groups items by ID in both before and after
2. For each ID in `afterGroups`, does pairwise positional matching against `beforeGroup`
3. Extra items in `after` (more duplicates) are reported as "added"
4. Extra items in `before` (fewer duplicates in after) are reported as "removed"
5. Items whose ID exists only in `before` are all reported as "removed"

**Edge cases verified:**

- `before=[A1, A2]`, `after=[A3]`: First pair is "changed", second `before` item is "removed"
- `before=[A1]`, `after=[A1, A2]`: First pair is "kept", second `after` item is "added"
- No duplicates: Same behavior as before (each group has exactly 1 item)

Tests added:

- `diff.test.ts:90-109`: Duplicate IDs with pairwise matching (2 before, 1 after)
- `diff.test.ts:111-121`: More duplicates in after than before

---

## High Issues

### H1: Shared `validatePackInputs()` extracted -- VERIFIED

**Status:** Fixed correctly.

`validatePackInputs()` is defined in `schemas.ts` (lines 37-71) and imported by both `pack.ts` and `stream.ts`. The function performs all three validation steps:

1. Budget schema validation via `BudgetSchema.safeParse`
2. `reserveTokens >= maxTokens` check
3. Items array validation via `z.array(ContextItemSchema).safeParse`

Both `pack.ts:internalPack` (line 140) and `stream.ts:packStream` (line 36) now call `validatePackInputs(items, budget)` as their first operation. The duplicated inline validation code has been removed from both files.

Existing tests in `pack.test.ts` and `stream.test.ts` exercise the validation paths (invalid budget, missing id, reserveTokens >= maxTokens).

### H2: O(n) sampling for large sets in quality analysis -- VERIFIED

**Status:** Fixed correctly.

The `analyzeContext` function in `quality.ts` (lines 114-139) now:

- Computes `totalPossiblePairs = n*(n-1)/2`
- If `<= MAX_PAIRS (5000)`: exhaustive comparison (unchanged)
- If `> MAX_PAIRS`: samples `min(5000, n*10)` deterministic pairs

The sampling uses `i = s % n` and `j = (i + 1 + Math.floor(s / n)) % n` with a guard `if (i !== j)` to skip self-pairs. This produces reproducible results and provides reasonable coverage by cycling through different offsets (1, 2, 3, ...) for each base index.

**Verified:** The `i !== j` guard is needed when `1 + Math.floor(s/n) = k*n` (happens at large sample counts). The guard correctly skips these cases.

A `jaccardSimilarity()` helper was extracted (lines 27-34), improving readability.

### H3: Freshness threshold documentation corrected -- VERIFIED

**Status:** Fixed correctly.

The `ContextQuality.freshness` JSDoc (quality.ts line 16) now reads: `"Freshness: fraction of items with recency > 5 on a 0-10 scale (0-1)"`. The inline comment (line 102) reads: `"Freshness: fraction of items with recency above midpoint (> 5 on 0-10 scale)"`. Both match the implementation `items.filter(item => (item.recency ?? 0) > 5)`.

### H4: Compression picks largest fitting variant -- VERIFIED

**Status:** Fixed correctly.

In `pack.ts:applyCompression` (line 40), the sort is now `(a, b) => b.tokens - a.tokens` (descending), and the dead `?? 0` after the `.map()` has been removed (line 40 uses `b.tokens` directly, not `b.tokens ?? 0`).

The same descending sort is applied in `stream.ts:tryCompress` (line 97).

This means the first fitting compression found in the loop is the largest one, maximizing content quality.

### H5 + H6: Shared `hash64` with improved collision resistance -- VERIFIED

**Status:** Fixed correctly.

A new `src/hash.ts` module (lines 1-36) exports `hash64()` which concatenates two independent 32-bit hashes:

1. DJB2-like: `h1 = ((h1 << 5) - h1 + charCode) | 0`
2. FNV-1a-like: `h2 ^= charCode; h2 = Math.imul(h2, 0x01000193)` with seed `0x811c9dc5`

Both `session.ts` (line 15) and `cache-topology.ts` (line 18) now import `hash64` from `./hash.js`. The local `quickHash` and `hashString` functions have been removed.

The 64-bit output space (two independent 32-bit hashes) pushes birthday-paradox collisions from ~65K inputs to ~4 billion inputs, which is adequate for cache identity.

`index.ts` line 11: `export * from "./hash.js"` makes `hash64` part of the public API.

### H7: Named exports in index.ts hide internal functions -- VERIFIED

**Status:** Fixed correctly.

`index.ts` line 6: `export { pack, packAsync } from "./pack.js"` replaces the previous `export * from "./pack.js"`. This means `internalPack` and `internalPackAsync` are no longer part of the public API surface.

`trace.ts` still imports `internalPack` directly from `./pack.js` (line 7), which works correctly since it's a direct file import within the package.

### H8: Unused `PackOptionsSchema` removed -- VERIFIED

**Status:** Fixed correctly.

`PackOptionsSchema` is no longer present in `schemas.ts`. The file now contains only `CompressionSchema`, `ContextItemSchema`, `BudgetSchema`, and `validatePackInputs()`.

### H9: `estimateTokens` accepts `string | null | undefined` -- VERIFIED

**Status:** Fixed correctly.

`estimate.ts` line 30: `text: string | null | undefined`. The implementation on line 33 (`if (text == null) return 0`) matches the type signature.

**Note:** The `TokenEstimator` interface in `types.ts` (line 97) still expects `(text: string, ...)`. This means if someone passes `null` to `estimateTokens`, the null check on line 33 catches it before the estimator is called, so no type mismatch at runtime. This is correct.

Existing tests in `estimate.test.ts` (lines 37-38) pass `null as unknown as string` and `undefined as unknown as string`. With the type change, the casts are technically no longer needed, but they still work. The fix summary notes this.

---

## Medium and Low Fixes

### M1: O(1) kind lookup in allocation.ts -- VERIFIED

**Status:** Fixed correctly.

`allocation.ts` line 95: `const allocatedKinds = new Set(allocations.map(a => a.kind))`. Line 103: `allocatedKinds.has(kind)` replaces the previous `allocations.find(a => a.kind === kind)`. The original code only needed a boolean existence check at this point (the allocation objects are used later in separate loops), so the `Set` replacement is correct.

### M5: Timestamp-as-recency normalized in causal compaction -- VERIFIED

**Status:** Fixed correctly.

`compaction.ts` lines 167-174: Timestamps are normalized to 0-10 scale:

```ts
const minTs = Math.min(...timestamps);
const maxTs = Math.max(...timestamps);
const tsRange = maxTs - minTs;
const normalizedRecency =
  tsRange > 0 ? (((t.timestamp ?? 0) - minTs) / tsRange) * 10 : 5;
```

Falls back to 5 when all timestamps are identical (`tsRange = 0`). This is correct: if all turns have the same timestamp, recency should not differentiate them, and 5 (midpoint) is a neutral value.

### M8: Redundant filter removed in compaction -- VERIFIED

**Status:** Fixed correctly.

The first `.filter(i => (i.tokens ?? 0) <= availableTokens)` has been removed from the item packing phase (compaction.ts lines 259-275). Only the greedy packing filter remains, which naturally handles oversized items.

### M9: Consistent default priority in causal scorer -- VERIFIED

**Status:** Fixed correctly.

`score.ts` line 73: `const priority = item.priority ?? 0`. Both `defaultItemScorer` (via `createScorer`) and `createCausalScorer` now use `?? 0` for missing priority values.

### M10: Unnecessary cast removed in compaction addTurn -- VERIFIED

**Status:** Fixed correctly.

`compaction.ts` line 114: `const taskId = turn.taskId ?? activeTaskId`. The unnecessary `(turn as { taskId?: string }).taskId` cast has been removed. Since the `addTurn` parameter type is `Omit<Turn, "tokens" | "timestamp">` and `Turn` includes `taskId?: string`, direct access works correctly.

### M14: Single word-split pass in quality analysis -- VERIFIED

**Status:** Fixed correctly.

`quality.ts` lines 69-74: `const itemWords = items.map(item => item.content.toLowerCase().split(/\s+/).filter(w => w.length > 0))`. This pre-computed array is reused for:

- Density (lines 82-88): iterating words to build `uniqueWords` set
- Diversity (lines 92-98): building bigrams
- Redundancy (lines 108-110): building word sets for Jaccard similarity

### M15: Mutable counter object replaced -- VERIFIED (bundled with H2/M14)

`quality.ts` line 92: `let totalBigramCount = 0` replaces the old `const totalBigrams = { count: 0 }`.

### L1: Redundant `as number` cast removed from score.ts -- VERIFIED

`score.ts` line 36: `? item.metadata.salience` (no cast). TypeScript narrows the type after the `typeof === "number"` check.

---

## Issues NOT Fixed (out of scope)

The following audit issues were not in the fix scope and remain unfixed. This is expected per the fix summary.

| Issue | Status    | Notes                                                                                                        |
| ----- | --------- | ------------------------------------------------------------------------------------------------------------ |
| M2    | Not fixed | `kindBudgets.set` in allocation.ts:220 still has the `?? result.used` fallback and inflated budget reporting |
| M3    | Not fixed | Redundancy "summarize" strategy still identical to "recent"                                                  |
| M4    | Not fixed | `preserveRecentTurns` edge case not documented                                                               |
| M6    | Not fixed | `BeadsIssue` index signature still weakens types                                                             |
| M7    | Not fixed | Cache LRU still creates iterator per eviction                                                                |
| M11   | Not fixed | Pipeline `+ 100` magic number remains                                                                        |
| M12   | Not fixed | `packAsync` still has no dedicated tests                                                                     |
| M13   | Not fixed | `addMany` unsafe cast in pipeline.ts remains                                                                 |
| M16   | Not fixed | ISO string comparison for `defer_until`                                                                      |
| M17   | Not fixed | Priority roundtrip lossy in BEADS                                                                            |
| L2-L9 | Not fixed | Various low-priority items                                                                                   |

---

## Overall Assessment

The fixes are well-executed. The code quality is high:

- **Binary search truncation (C2):** Correctly replaces the character heuristic with measured token counts. The word-boundary approach is a good balance between precision and simplicity.
- **Diff duplicate handling (C4):** Group-based pairwise matching is the right approach. Positional matching within groups is deterministic and predictable.
- **packStream compression (C3):** Mirrors `pack()` behavior closely. The `tryCompress` helper is clean and correct.
- **hash64 (H5+H6):** DJB2 + FNV-1a combination is a well-known technique for producing independent hash values. Adequate for non-cryptographic cache identity.
- **Shared validation (H1):** Clean extraction, no behavioral change.
- **Quality sampling (H2):** Deterministic and reproducible. Good coverage without O(n^2) cost.

No fixes were found to introduce new bugs. No corrections were necessary.
