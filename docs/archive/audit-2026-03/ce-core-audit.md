# ce-core Deep Audit

**Date:** 2026-03-17
**Auditor:** Claude Opus 4.6 (1M context)
**Package:** `@context-engineering/core` v0.1.0
**Files reviewed:** 25 source files, 26 test files (including 3 snapshots)

## Summary

The ce-core package is well-structured with clean separation of concerns across ~25 modules. The core algorithms (pack, score, estimate, diff) are solid. Documentation is excellent with JSDoc on every public function. Test coverage is good across happy paths.

However, this audit found **4 critical issues**, **9 high-priority issues**, **18 medium-priority issues**, and numerous lower-priority items. The most concerning patterns are: a dead code variable that signals incomplete implementation, duplicated validation logic across pack/stream (DRY violation), an O(n^2) quality analysis that will blow up on large item sets, and several edge cases in the compaction module that can silently lose data.

**Stats:**

- 25 source files (~2,200 LOC)
- 26 test files (~2,400 LOC)
- 1 dependency (zod)
- 0 uses of `any` in source (good)
- 3 explicit `as` casts in source (acceptable)

---

## Critical Issues

### C1. `_previousSelectedIds` is dead state in session.ts (lines 150, 264, 288)

```ts
// session.ts:150
let _previousSelectedIds = new Set<string>();

// session.ts:264
_previousSelectedIds = new Set(currentManifest.map(e => e.id));

// session.ts:288
_previousSelectedIds = new Set();
```

This variable is written to but **never read**. It is updated on every compile and cleared on reset, but no code ever consumes it. This is either dead code from a removed feature, or a bug where something that should be using this set is instead recomputing it. Given the session module tracks deltas, this could mean a planned optimization (e.g., fast-path "was this item in the previous set?") was never wired up. The underscore prefix suggests awareness, but it still ships unused state that gets recalculated on every compile.

**Severity:** CRITICAL (dead state that signals potentially incomplete logic)
**Fix:** Remove the variable entirely, or wire it into the delta computation where it was likely intended to replace the `prevMap` construction on line 190.

### C2. Compaction truncation uses character count as token proxy (compaction.ts:199)

```ts
const targetTokens = Math.floor(availableTokens * 0.3);
const truncated = combinedContent.slice(0, targetTokens * 4);
```

This assumes 1 token = 4 characters, which is a rough average for English but wildly inaccurate for code (closer to 1:3), CJK text (closer to 1:1.5), or JSON (highly variable). The `targetTokens * 4` heuristic can produce summaries that are 2x over budget for code-heavy conversations, silently exceeding the budget.

**Severity:** CRITICAL (silent budget violation in production use cases)
**Fix:** Use the configured `estimate()` function to actually measure the truncated content, then binary-search or iteratively trim to fit. Alternatively, truncate by estimated tokens using the estimator rather than by character count.

### C3. `packStream` does not support compression (stream.ts)

The synchronous `pack()` supports `allowCompression` + compressions + summarizer. The `packStream()` async generator does **none** of this. Items that exceed budget are silently dropped even when a compression exists that would fit. The test at stream.test.ts:50-66 documents this as intentional behavior, but this creates a silent API inconsistency where switching from `pack()` to `packStream()` loses items.

```ts
// stream.ts:88-93 - no compression attempt
for (const item of sorted) {
  if ((item.tokens ?? 0) <= remaining) {
    remaining -= item.tokens ?? 0;
    yield item;
  }
}
```

**Severity:** CRITICAL (behavioral inconsistency between pack and packStream that silently drops items)
**Fix:** Either implement compression support in packStream, or throw/warn when `allowCompression` is set in packStream options. At minimum, document this gap prominently.

### C4. `diff()` silently drops duplicate items (diff.ts:37-38)

```ts
const beforeMap = new Map(beforeItems.map(item => [item.id, item]));
const afterMap = new Map(afterItems.map(item => [item.id, item]));
```

When duplicate IDs exist (which `pack()` allows -- see pack.test.ts:184-192), the Map constructor keeps only the **last** entry for each ID. The first occurrence is silently lost. The diff will report fewer items than actually exist, and the "removed" count will be wrong. The test at diff.test.ts:90-105 documents this behavior but treats it as acceptable when it should arguably be a validation error or at least a warning.

Meanwhile, `pack()` happily processes duplicate IDs (pack.test.ts:184-192), scoring and selecting both copies. This means pack can select 2 items with ID "dupe", but diff will only see 1, making the diff unreliable for packs containing duplicates.

**Severity:** CRITICAL (data loss in diff computation; inconsistent with pack's duplicate handling)
**Fix:** Either validate uniqueness of IDs in pack (rejecting duplicates), or handle duplicates in diff by using arrays instead of Maps, or by using composite keys (id + index).

---

## High Priority

### H1. Massive validation duplication between pack.ts and stream.ts

Lines pack.ts:144-176 and stream.ts:34-63 contain **identical** validation logic: parse budget with BudgetSchema, check reserveTokens >= maxTokens, parse items with ContextItemSchema array. This is ~40 lines of exact duplication.

```ts
// Identical blocks in both files:
const budgetResult = BudgetSchema.safeParse(budget);
if (!budgetResult.success) {
  throw new ValidationError(...)
}
if (budget.reserveTokens !== undefined && budget.reserveTokens >= budget.maxTokens) {
  throw new BudgetExceededError(...)
}
const itemsResult = z.array(ContextItemSchema).safeParse(items);
if (!itemsResult.success) {
  throw new ValidationError(...)
}
```

**Severity:** HIGH (DRY violation; changes to validation must be made in two places)
**Fix:** Extract a shared `validatePackInputs(items, budget)` function.

### H2. O(n^2) pairwise comparison in quality.ts:103-117

```ts
for (let i = 0; i < itemWordSets.length; i++) {
  for (let j = i + 1; j < itemWordSets.length; j++) {
    // Jaccard similarity for every pair
  }
}
```

For n items, this performs n\*(n-1)/2 Jaccard computations. With 1000 items, that is ~500,000 set intersection operations, each iterating the smaller set. This will be noticeably slow for large context sets (e.g., RAG with hundreds of documents).

**Severity:** HIGH (performance degradation at scale)
**Fix:** For large n, use MinHash / LSH approximation, or cap the pairwise comparison at a sample size (e.g., randomly sample 50 pairs when n > 100).

### H3. `quality.ts` freshness threshold hardcoded and mismatched with docs (line 88)

```ts
// quality.ts:88 - actual code
const freshCount = items.filter(item => (item.recency ?? 0) > 5).length;
```

```ts
// quality.ts:87 - comment
// Freshness: fraction of items with recency > 5 (on 0-10 scale)
```

The interface comment on line 18 says "Freshness: fraction of items with recency > 0.5 (0-1)". The actual code uses `> 5` on a 0-10 scale. The JSDoc says 0-1 scale but the code operates on 0-10. Users reading the interface will expect `recency: 0.6` to count as fresh, but it won't.

**Severity:** HIGH (documented behavior does not match implementation)
**Fix:** Update the interface comment to accurately reflect the 0-10 scale threshold of 5, or make the threshold configurable.

### H4. `applyCompression` sorts by tokens but tokens are already computed (pack.ts:35-44)

```ts
const sorted = compressions
  .map(compression => ({
    ...compression,
    tokens: compression.tokens ?? estimateTokens(compression.content, {...}),
  }))
  .sort((a, b) => (a.tokens ?? 0) - (b.tokens ?? 0));
```

After the `.map()`, every compression has a guaranteed `tokens` value (either original or estimated). The `.sort()` comparison `(a.tokens ?? 0)` still uses nullish coalescing, which is dead code after the map. Minor, but the `?? 0` is misleading -- it suggests tokens could be undefined when it cannot be.

Additionally, the sort is ascending (smallest compression first), and the loop picks the first one that fits. This means it picks the **smallest** compression that fits, not necessarily the best quality one. If a compression has 30 tokens and another has 25, and both fit, the 25-token one wins even if it's a worse summary.

**Severity:** HIGH (compression selection strategy may not be optimal)
**Fix:** Remove dead `?? 0` after the map. Consider sorting by some quality heuristic or picking the largest compression that fits (more content = likely better quality).

### H5. `hashString` / `quickHash` are identical functions in two files

```ts
// cache-topology.ts:117-123
function hashString(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash + char) | 0;
  }
  return (hash >>> 0).toString(36);
}

// session.ts:68-73
function quickHash(str: string): string {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return (hash >>> 0).toString(36);
}
```

Same algorithm, different names, in two files.

**Severity:** HIGH (code duplication)
**Fix:** Extract to a shared utility, e.g., in a `utils.ts` file or alongside the logger.

### H6. Cache key uses weak 32-bit hash with high collision risk (cache-topology.ts, session.ts)

The `hashString`/`quickHash` functions produce a 32-bit hash encoded as base-36. With the birthday paradox, collisions become likely at ~65,000 unique inputs. For a caching system where correctness depends on "same hash = safe to reuse cached KV state," a collision means silently serving stale cache data to the model, which could produce incorrect outputs.

**Severity:** HIGH (correctness risk in cache identity)
**Fix:** Use a proper hash function. Even `crypto.subtle.digest('SHA-256', ...)` would work for non-cryptographic cache identity, or use a 64-bit hash at minimum. Alternatively, document that this is a hint, not a guarantee.

### H7. `internalPackAsync` is exported but appears to be internal API (pack.ts:125)

```ts
export async function internalPackAsync(...)
```

The name says "internal" but it's exported. The `internalPack` function is also exported and used by `trace.ts`. These should either be truly internal (not exported from index.ts) or renamed to not have "internal" in the name.

Checking index.ts: `export * from "./pack.js"` -- this means `internalPack` and `internalPackAsync` are both part of the public API surface, despite their names.

**Severity:** HIGH (confusing public API; consumers may depend on "internal" functions)
**Fix:** Either stop exporting them from index.ts (use named exports instead of star exports for pack.ts), or rename them to reflect their actual public status (e.g., `packWithTrace`, `packAsync`).

### H8. `PackOptionsSchema` doesn't validate `weights` or `redundancyConfig` (schemas.ts:29-36)

```ts
export const PackOptionsSchema = z
  .object({
    tokenEstimator: z.function().optional(),
    scorer: z.function().optional(),
    summarizer: z.function().optional(),
    allowCompression: z.boolean().optional(),
  })
  .optional();
```

The `PackOptions` type in types.ts includes `weights`, `logger`, and `redundancyConfig`, but the schema only validates 4 of the 7 fields. Moreover, `PackOptionsSchema` is defined but **never used** in pack.ts -- pack.ts validates budget and items, but not options.

**Severity:** HIGH (incomplete validation schema; schema is defined but unused)
**Fix:** Either complete the schema and actually use it in pack(), or remove it to avoid false confidence.

### H9. `estimateTokens` accepts null via loose `==` check but type says `string` (estimate.ts:33)

```ts
export function estimateTokens(
  text: string,  // <-- type says string
  options?: ...
): number {
  if (text == null) return 0;  // <-- handles null/undefined
```

The function signature says `text: string` but the implementation handles `null` and `undefined`. The test at estimate.test.ts:37-38 explicitly tests `null as unknown as string` and `undefined as unknown as string`. This is defensive programming that works at runtime but lies in the types. Callers who trust the types will never pass null, and callers who do pass null are violating the type contract.

**Severity:** HIGH (type/implementation mismatch)
**Fix:** Either change the signature to `text: string | null | undefined` (honest), or remove the null check and let callers handle it (strict). The current approach creates type-level confusion.

---

## Medium Priority

### M1. `allocation.ts:100` uses `.find()` inside a loop (O(n\*m))

```ts
for (const item of items) {
  const kind = item.kind ?? "_uncategorized";
  const alloc = allocations.find(a => a.kind === kind); // O(m) per item
```

For each item, it does a linear scan of allocations. With many items and many allocation categories, this is O(items \* allocations). Should use a Map for O(1) lookup.

**Severity:** MEDIUM
**Fix:** `const allocMap = new Map(allocations.map(a => [a.kind, a]))` before the loop.

### M2. `allocation.ts:218` updates `kindBudgets` incorrectly during surplus redistribution

```ts
kindBudgets.set(
  alloc.kind,
  (kindBudgets.get(alloc.kind) ?? result.used) + extraPack.totalTokens
);
```

The fallback `?? result.used` makes no sense -- if `kindBudgets` doesn't have the kind, we shouldn't be redistributing to it. This line also adds `extraPack.totalTokens` to the allocated budget, but the budget was already consumed by packing. The `kindBudgets` map is only read later in the final reporting (line 253), so this inflates the `budgetAllocated` number in the final result.

**Severity:** MEDIUM (incorrect reporting of budget allocation after redistribution)
**Fix:** Track allocated vs. used separately, or just report `result.used` as the final allocated amount.

### M3. `redundancy.ts` "summarize" strategy is identical to "recent" (lines 70-86)

```ts
if (strategy === "recent" || strategy === "summarize") {
  // ... identical logic for both strategies
}
```

The `summarize` strategy was presumably meant to combine cluster items into a summary, but it just picks the most recent item, same as `recent`. The test at redundancy.test.ts:77-88 documents this as "fallback to recency when LLM is unmocked," but there's no actual summarization path.

**Severity:** MEDIUM (dead/stub feature advertised in the API)
**Fix:** Either implement actual summarization (using a Summarizer callback), or remove the "summarize" strategy option and document that only "recent" is supported.

### M4. `compaction.ts:149` slice with `preserveRecent=0` produces `turns.slice(0, 0)` for olderTurns

```ts
const recentTurns = preserveRecent > 0 ? turns.slice(-preserveRecent) : [];
const olderTurns = preserveRecent > 0 ? turns.slice(0, -preserveRecent) : turns;
```

When `preserveRecent = 0`, `recentTurns = []` and `olderTurns = turns`. This is correct. But when `preserveRecent >= turns.length`, `turns.slice(0, -preserveRecent)` returns an empty array (negative index beyond array start), so all turns go to `recentTurns` and none to `olderTurns`. This means if you have 3 turns and `preserveRecentTurns: 10`, all 3 are "recent" and none get compacted. This is probably the desired behavior, but it's non-obvious.

**Severity:** MEDIUM (implicit behavior that should be documented)

### M5. `compaction.ts:176` uses raw `t.timestamp` as recency for scoring

```ts
const item: ContextItem = {
  // ...
  recency: t.timestamp, // Unix timestamp in milliseconds!
};
```

`t.timestamp` is a Unix timestamp in milliseconds (e.g., 1710000000000). This is passed as `recency` to the scorer, which multiplies it by 0.7. The resulting score will be astronomically large (~1.2 trillion), completely dominating the priority component. This means the causal scorer's priority-based weighting is meaningless -- recency (timestamp) always wins.

**Severity:** MEDIUM (scoring is effectively broken for causal compaction with timestamps as recency)
**Fix:** Normalize the timestamp to a 0-10 scale (like bridge.ts does with exponential decay), or use an index-based recency within the compaction context.

### M6. `BeadsIssue` interface uses index signature `[key: string]: unknown` (beads.ts:128)

```ts
export interface BeadsIssue {
  id: string;
  title: string;
  // ... many typed fields ...
  [key: string]: unknown; // <-- this weakens all type checking
}
```

The index signature means TypeScript will not flag typos in property names when constructing BeadsIssue objects. You can write `issue.titl = "typo"` without error. This undermines the purpose of having typed fields.

**Severity:** MEDIUM (type safety weakened)
**Fix:** Use a separate `extensions?: Record<string, unknown>` field for unknown properties, or use a branded type.

### M7. `cache.ts` LRU eviction only removes one entry (lines 44-49)

```ts
if (cache.size >= maxSize) {
  const firstKey = cache.keys().next().value;
  if (firstKey !== undefined) {
    cache.delete(firstKey);
  }
}
```

This evicts exactly one entry when at capacity. This works because Map preserves insertion order and the first key is the oldest. However, if `estimator` is called in a tight loop with many unique inputs, each call evicts one old entry and adds one new entry, maintaining the size at exactly `maxSize`. This is correct but could cause performance issues because `cache.keys().next()` creates an iterator on every eviction. For hot paths, consider a proper LRU with doubly-linked list.

**Severity:** MEDIUM (performance concern at scale; functionally correct)

### M8. `compaction.ts:231-241` filter + filter is redundant

```ts
selectedItems = items
  .map(i => ({ ...i, tokens: i.tokens ?? estimate(i.content) }))
  .map(i => ({ ...i, score: itemScorer(i) }))
  .filter(i => (i.tokens ?? 0) <= availableTokens) // filter 1
  .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

let usedTokens = 0;
selectedItems = selectedItems.filter(item => {
  // filter 2
  if (usedTokens + (item.tokens ?? 0) <= availableTokens) {
    usedTokens += item.tokens ?? 0;
    return true;
  }
  return false;
});
```

The first filter removes items individually larger than `availableTokens`. The second filter does greedy packing. The first filter is redundant because the second filter will naturally skip any item that doesn't fit. The only case where filter 1 matters is if a single item is larger than the entire available budget and appears before smaller items in score order -- but the second filter handles that too.

**Severity:** MEDIUM (unnecessary computation)
**Fix:** Remove the first `.filter()`.

### M9. `score.ts:73` default priority differs from `defaultItemScorer` (createCausalScorer)

```ts
// defaultItemScorer (line 32):
const priority = item.priority ?? 0;

// createCausalScorer (line 73):
const priority = item.priority ?? 5;
```

When `item.priority` is undefined, the default scorer uses 0 but the causal scorer uses 5. This means items without explicit priority get scored very differently depending on which scorer is active. Switching from default scoring to causal scoring silently boosts all un-prioritized items.

**Severity:** MEDIUM (inconsistent defaults between scorers)
**Fix:** Use the same default (probably 0) in both scorers, or document the difference.

### M10. `compaction.ts:115` accesses `taskId` via unsafe cast

```ts
function addTurn(turn: Omit<Turn, "tokens" | "timestamp">): void {
  const tokens = estimate(turn.content);
  const taskId = (turn as { taskId?: string }).taskId ?? activeTaskId;
```

The `Omit<Turn, "tokens" | "timestamp">` type still includes `taskId`, so this cast is unnecessary. `turn.taskId` would work directly since `taskId` is defined on the `Turn` interface. The cast obscures this.

**Severity:** MEDIUM (unnecessary cast; confusing)
**Fix:** Just use `turn.taskId ?? activeTaskId`.

### M11. `pipeline.ts:246` magic number `+ 100` in cache topology re-packing

```ts
if (this.cacheTopologyConfig) {
  stages.push("cacheTopology");
  const cacheResult = packWithCacheTopology(
    selected,
    { maxTokens: totalTokens + 100 }, // generous budget since already packed
```

The `+ 100` is a magic number with only a comment for justification. If the pre-packed items total exactly `totalTokens`, adding 100 extra tokens of headroom should be fine. But if token estimates differ between the first pack and the cache-topology pack (e.g., due to rounding), items could be silently dropped during re-packing.

**Severity:** MEDIUM (fragile; magic number)
**Fix:** Use `Infinity` or `Number.MAX_SAFE_INTEGER` if the intent is "don't drop anything, just reorder." Or pass the items directly without re-packing.

### M12. No test for `packAsync` (pack.ts:108-115)

The `packAsync` function is exported and part of the public API. It wraps `internalPackAsync` which handles redundancy elimination. There are no tests for `packAsync` in pack.test.ts or any other test file.

**Severity:** MEDIUM (untested public API)
**Fix:** Add tests for `packAsync`, including with and without `redundancyConfig`.

### M13. `addMany` in pipeline.ts uses unsafe cast (line 117)

```ts
addMany(items: ContextItem[], defaults?: Partial<ContextItem>): this {
  for (const item of items) {
    this.items.push({ ...defaults, ...item } as ContextItem);
  }
```

The `as ContextItem` cast is needed because `{ ...defaults, ...item }` might not satisfy `ContextItem` if neither `defaults` nor `item` has all required fields. But the cast silences the compiler rather than validating. If someone calls `.addMany([{ tokens: 5 } as ContextItem], {})`, the cast will hide the missing `id` and `content`, leading to a runtime validation error later in pack().

**Severity:** MEDIUM (unsafe cast could hide invalid items)
**Fix:** Validate that required fields exist, or change the type to require items to already be valid ContextItems.

### M14. `quality.ts` word splitting done 3 times for the same items (lines 62-101)

Items' content is split into words three separate times:

1. Lines 62-67: `allWords` for density
2. Lines 74-82: `words` per item for bigrams
3. Lines 94-101: `itemWordSets` for redundancy

Each split creates new arrays and sets. For large content, this triples the allocation cost.

**Severity:** MEDIUM (inefficiency; redundant work)
**Fix:** Compute word arrays once per item and reuse.

### M15. `quality.ts:73` uses mutable object for counter

```ts
const totalBigrams = { count: 0 };
```

Using an object wrapper for a counter is unusual in this codebase. A simple `let totalBigramCount = 0` would be clearer and avoid the object allocation.

**Severity:** LOW (style; unnecessary indirection)

### M16. `getReadyIssues` uses ISO string comparison for defer_until (beads.ts:584)

```ts
if (issue.defer_until && issue.defer_until > now) return false;
```

ISO 8601 strings sort lexicographically the same as chronologically (for the same timezone), so this works correctly. However, it relies on both dates being in the same format. If `defer_until` uses a different ISO format or timezone offset, the comparison could be wrong.

**Severity:** MEDIUM (fragile date comparison)
**Fix:** Compare as `new Date(issue.defer_until) > new Date(now)` for robustness.

### M17. `contextItemToBeads` priority mapping is lossy (beads.ts:240-243)

```ts
const beadsPriority = Math.max(
  0,
  Math.min(4, 4 - Math.floor(((item.priority ?? 5) / 10) * 4))
);
```

This maps priority 0-10 to BEADS 0-4 with `Math.floor`, which means priorities 1 and 2 both map to BEADS 4, priorities 3 and 4 both map to BEADS 3, etc. The reverse mapping in `beadsToContextItem` (line 308) uses `Math.round(((4 - issue.priority) / 4) * 10)`, which is not the exact inverse. Roundtripping priority 7 gives: 7 -> BEADS 1 -> back to 8. Priority is not preserved through roundtrip.

**Severity:** MEDIUM (lossy roundtrip)
**Fix:** Store original priority in \_ce metadata (which is already done at line 271), and always prefer it on recovery (which is done at line 307). The lossy conversion is only used as fallback, so this is acceptable but should be documented.

### M18. Unused import: `EstimationError` in pack.ts line 14

```ts
import {
  ValidationError,
  BudgetExceededError,
  EstimationError, // imported
} from "./errors.js";
```

`EstimationError` is imported and also used on line 198. Wait -- it IS used. Let me re-check... Yes, line 198: `throw new EstimationError(...)`. This is actually fine. Removing this finding.

**Revised M18.** No issue here -- false positive on review.

---

## Low Priority

### L1. `score.ts` line 37: `as number` cast is redundant

```ts
const salience =
  typeof item.metadata?.salience === "number"
    ? (item.metadata.salience as number) // cast unnecessary after typeof check
    : 0;
```

After `typeof x === "number"`, TypeScript already narrows the type to `number`. The `as number` cast is redundant (though harmless).

**Severity:** LOW
**Fix:** Remove `as number`.

### L2. `bridge.ts:40` exponential decay can produce negative recency for future timestamps

```ts
const ageSeconds = (now - new Date(memory.createdAt).getTime()) / 1000;
const recency = Math.pow(0.5, ageSeconds / halfLife) * 10;
```

If `createdAt` is in the future (e.g., clock skew), `ageSeconds` is negative, and `Math.pow(0.5, negative)` produces a value > 1, giving recency > 10. The 0-10 scale is violated.

**Severity:** LOW (edge case; unlikely in practice)
**Fix:** Clamp ageSeconds to `Math.max(0, ageSeconds)`.

### L3. `pipeline.ts` imports `ContextSession` and `SessionDelta` but uses them only as types

```ts
import { type ContextSession, type SessionDelta } from "./session.js";
```

This is fine -- using `type` imports. No issue.

### L4. `webhook.ts:201` timer is cleared in both `.then()` and `.catch()` but not in `.finally()`

```ts
fetch(url, { ... })
  .then(() => { clearTimeout(timer); })
  .catch((err: unknown) => { clearTimeout(timer); ... });
```

Using `.finally()` would be cleaner and guarantee the timer is cleared even if the promise is handled in unexpected ways.

**Severity:** LOW (style)
**Fix:** Move `clearTimeout(timer)` to a `.finally()` block.

### L5. `compaction.ts` compile method is ~110 lines long

The `compile()` function (lines 139-251) has 4 phases spanning 110+ lines. It handles causal scoring, fallback summarization, greedy packing of turns, and greedy packing of items. Each phase could be extracted into a named function for readability.

**Severity:** LOW (readability; function too long per project conventions of <30 lines)
**Fix:** Extract phases into `compactWithCausalScorer()`, `compactWithSummarization()`, `compactOlderTurns()`, and `packContextItems()`.

### L6. `recommendations.ts:99` return type annotation `Promise<unknown | null>` is redundant

```ts
async function fetchJson(...): Promise<unknown | null> {
```

`unknown | null` is just `unknown` since `null` is a subtype of `unknown`. The `| null` adds no information.

**Severity:** LOW (type pedantry)
**Fix:** Use `Promise<unknown>`.

### L7. Test snapshots may be brittle

Three snapshot files exist (`pack.test.ts.snap`, `diff.test.ts.snap`, `trace.test.ts.snap`). Snapshots are useful for regression detection but can be brittle -- any change to token estimation, scoring, or item structure will break them. The snapshots should be reviewed periodically.

**Severity:** LOW (maintenance concern)

### L8. `beads.ts:289` uses nested `as` casts for metadata access

```ts
const ceMetadata = (issue.metadata as Record<string, unknown>)?._ce as
  | Record<string, unknown>
  | undefined;
```

This double-cast chain is fragile. If `metadata` is not a Record, the `?._ce` access could fail in unexpected ways.

**Severity:** LOW (defensive coding already present; style improvement possible)
**Fix:** Use a helper function to safely extract nested metadata.

### L9. `compaction.ts:92-93` variable `effectiveBudget` shadows import possibility

The local variable `effectiveBudget` in `createContextManager` has the same name as the exported function in `placement.ts`. While there's no actual import collision here, it could confuse developers navigating the codebase.

**Severity:** LOW (naming)

---

## Notes & Questions

### N1. `tsconfig.json` targets ES2020 but package.json requires Node >= 18

Node 18 supports ES2022. The target could be bumped to ES2022 to match the engines requirement and enable features like `Array.at()`, top-level await, and error cause.

### N2. Zod v4 is used (package.json: `"zod": "^4.1.12"`)

Zod 4 is a significant breaking change from Zod 3. Make sure all consumers of this package are also on Zod 4, or consider the compatibility implications if this is a published library.

### N3. `PackOptionsSchema` is exported but never used internally

It's defined in schemas.ts and exported, but pack.ts doesn't use it to validate options. Either it's intended for external use (CLI validation?), or it's vestigial.

### N4. `causal-compaction.test.ts` uses `as any` to pass `taskId` to addTurn

```ts
ctx.addTurn({ role: "user", content: "...", taskId: "root" } as any);
```

The `addTurn` signature accepts `Omit<Turn, "tokens" | "timestamp">`, which should include `taskId`. The `as any` cast suggests the type isn't flowing correctly, which may indicate a type issue in the Turn/addTurn interface.

### N5. No explicit test for the `addItems` accumulation behavior in compaction

Items added via `addItems` accumulate across calls. If you call `addItems` twice with the same IDs, you get duplicates. This differs from `session.ts:addItems` which deduplicates. The inconsistency is not tested.

### N6. The `ScoringWeights` type doesn't constrain values

There's no validation that weights are non-negative or finite. Negative weights would invert scoring (higher priority = lower score), and NaN/Infinity weights would produce NaN scores. The schema validates item fields but not weights.

### N7. `recommendations.ts` calls `recommendationOptionsFromEnv()` on every fetch

Both `fetchBudgetRecommendation` and `fetchWeightConfig` call `recommendationOptionsFromEnv()` internally, reading `process.env` on every invocation. This is fine for most cases but could be surprising in hot paths.

---

## Good Patterns

### G1. Clean error hierarchy

`ContextEngineeringError` -> `ValidationError` / `BudgetExceededError` / `EstimationError` with string `code` fields. Well-designed, consistent with both TS and Python SDKs.

### G2. Logger interface

The `Logger` interface is minimal and compatible with console, pino, winston. The `noopLogger` default means logging never interferes with core functionality. Every log-capable function accepts an optional logger.

### G3. Zod validation at the boundary

Using Zod schemas to validate pack inputs (items and budget) at the function boundary is good practice. Error messages include path and detail information useful for debugging.

### G4. Defensive `estimateTokens` wrapping

The `estimateTokens` function catches estimator errors and wraps them in `EstimationError`, providing consistent error types to callers regardless of which estimator is used.

### G5. Immutable patterns throughout

Functions consistently use `[...array]`, `{ ...object }` spread to avoid mutating inputs. `pack()` creates copies of scored items. `placeItems()` returns a new array. `toContextItem()` creates new objects.

### G6. Pluggable architecture

Token estimators, scorers, summarizers, and loggers are all injectable via interfaces. The defaults are sensible (heuristic estimation, standard weights, noop logging). This makes the library testable and extensible.

### G7. Comprehensive JSDoc

Every public function has JSDoc with `@param`, `@returns`, `@throws`, and `@example`. Examples are practical and copy-pasteable.

### G8. Pipeline builder pattern

The `ContextPipeline` class provides a fluent API that composes all the individual pieces. Stage ordering is handled internally regardless of method call order. This is good DX.

### G9. Session delta tracking

The session module's approach to computing deltas via content hashing and manifest comparison is well-designed. The `unchangedPrefix` function correctly identifies the reusable KV cache portion.

### G10. Test quality

Tests focus on behavior, use descriptive names, follow Arrange-Act-Assert, and cover edge cases (empty inputs, boundary values, error conditions). The integration tests verify real multi-module workflows.

---

## File-by-File Detail

### types.ts

- **Clean.** Simple interfaces, no logic bugs. `createContextItem` is a nice convenience factory.
- Types are well-structured with optional fields having sensible semantics.
- The `ContextItem` interface has grown with BEADS fields (taskId, isOutcome, dependsOn) -- consider whether these belong on the core type or a BEADS-specific extension.

### errors.ts

- **Clean.** Proper class hierarchy. `name` is set correctly for each class. `code` field enables programmatic error handling.
- Minor: no `cause` support (Error.cause from ES2022). Would be useful for wrapping underlying errors.

### schemas.ts

- `PackOptionsSchema` is defined but never used in pack validation (see H8).
- `ContextItemSchema` doesn't validate BEADS fields (taskId, isOutcome, dependsOn) -- they're accepted silently via `.passthrough()` default behavior of Zod objects, but not validated.

### estimate.ts

- Type says `string`, implementation handles null (see H9).
- Otherwise clean and well-tested.

### score.ts

- Redundant `as number` cast (see L1).
- Inconsistent default priority between scorers (see M9).
- `createCausalScorer` is well-structured with multiplier-based scoring.

### pack.ts

- Validation duplication with stream.ts (see H1).
- Compression picks smallest fitting variant, not best quality (see H4).
- `internalPack` and `internalPackAsync` exported despite "internal" name (see H7).
- `packAsync` has no tests (see M12).

### diff.ts

- Silent duplicate handling (see C4).
- `normalize()` helper correctly extracts items from ContextPack.
- Change detection checks both `content` and `tokens` but not other fields -- metadata changes are not detected.

### trace.ts

- **Clean.** Simple delegation to `internalPack` with `trace=true`. ISO timestamp generation.

### stream.ts

- No compression support (see C3).
- Validation duplication (see H1).
- Good async generator pattern.

### cache.ts

- **Clean.** Simple and correct LRU-ish cache. Eviction could be faster for hot paths (see M7).

### bridge.ts

- Future timestamps produce recency > 10 (see L2).
- Well-tested with good integration tests against the scorer.

### quality.ts

- O(n^2) redundancy calculation (see H2).
- Freshness threshold mismatch with docs (see H3).
- Triple word splitting (see M14).
- Mutable counter object (see L3/M15).

### redundancy.ts

- "summarize" strategy is a stub (see M3).
- `cosineSimilarity` handles zero-magnitude vectors correctly (returns 0).
- Clustering is single-pass (first-fit), which means cluster quality depends on item order. Not necessarily wrong, but worth noting.

### placement.ts

- **Clean.** Well-structured attention profiles. The placement algorithm correctly assigns highest-scored items to highest-attention positions.
- `effectiveBudget` is a useful utility function.

### compaction.ts

- Truncation uses character count as token proxy (see C2).
- Timestamp used as raw recency value (see M5).
- Unsafe cast for taskId access (see M10).
- Long compile method (see L5).
- Redundant filter (see M8).
- `preserveRecentTurns` edge case (see M4).

### cache-topology.ts

- Duplicated hash function (see H5).
- Weak hash with collision risk (see H6).
- `classifyVolatility` uses `metadata.volatility as Volatility` without validation -- any string would be accepted.
- Otherwise well-designed with clear partitioning logic.

### allocation.ts

- O(n\*m) find-in-loop (see M1).
- Incorrect budget reporting after redistribution (see M2).
- Over-allocation normalization handles the case where minTokens sum exceeds budget by reducing lower-priority allocations first, then cutting into minimums. This is a reasonable strategy.
- Two-pass normalization (lines 130-155) is correct but could be one pass.

### session.ts

- Dead `_previousSelectedIds` variable (see C1).
- Duplicated hash function (see H5).
- Delta computation is thorough and well-tested.
- `addItems` correctly deduplicates by ID (new items override existing).

### beads.ts

- Index signature weakens types (see M6).
- Priority roundtrip is lossy (see M17).
- `readBeadsJSONL` silently skips malformed lines with empty catch -- this is intentional per BEADS spec tolerance.
- `getReadyIssues` uses string comparison for dates (see M16).
- `createHandoff` and `pickupHandoff` roundtrip well per integration tests.

### pipeline.ts

- Magic number `+ 100` (see M11).
- Unsafe cast in `addMany` (see M13).
- Quality gate drops items in a while loop that re-analyzes quality each iteration -- this is correct but potentially slow for large item sets (O(n^2) in worst case, removing one item at a time).
- `ContextPipeline` is a class (unusual in this codebase which favors functions), but the builder pattern justifies it.

### cost.ts

- **Clean.** Pricing data is well-structured. Math is correct per spot-checking.
- Pricing will need periodic updates as model prices change. Consider making this configurable via a remote source.

### webhook.ts

- Timer cleanup pattern (see L4).
- Otherwise well-structured fire-and-forget pattern. The `noopReporter` is a good default.
- `TextEncoder` is used to compute `jsonl_size_bytes` -- this is correct (measures UTF-8 byte length, not character count).

### recommendations.ts

- `fetchJson` return type annotation is redundant (see L6).
- Defensive programming throughout -- never throws, always returns fallback. This is the right design for an external data source.
- Environment variable reading on every call (see N7).

### index.ts

- Star exports from all modules, plus named exports for pipeline. This means all "internal" functions are publicly exported (see H7).
- Export ordering roughly matches dependency order, which is good.
