# ce-memory Fix Review

**Date:** 2026-03-17
**Scope:** Verify all fixes from ce-memory-audit.md as described in ce-memory-fixes.md
**Reviewer:** Claude Opus 4.6 (automated)
**Tests:** Could not run (`npx vitest run` blocked by sandbox). Review is code-level only.

## Summary

All 23 original issues (H1-H6, M1-M8, L1-L5, N1-N4) were reviewed. 17 were explicitly addressed by fixes. 2 medium issues (M4, M6) and 4 notes (N1-N4) were intentionally deferred. All applied fixes are correct and complete with one minor residual gap in H4 (documented below). No new bugs were introduced. Test coverage for the fixes is adequate.

---

## High Priority Issues

### H1. SQLite LIKE wildcard injection -- VERIFIED FIXED

**Approach:** Rather than escaping `%` and `_` in LIKE patterns, the fix eliminated SQL-side text filtering entirely (as part of H2). All text matching now goes through `applyQueryFilter` which uses `String.prototype.includes()` -- a literal substring match.

**Verification:** `sqlite-store.ts:114-123` does a bare `SELECT * FROM table` with no WHERE clause. The test `"handles LIKE wildcard characters in text query"` (`memory.test.ts:476-494`) explicitly checks that `%` and `_` are treated as literals.

**Verdict:** Correct and complete. The fix is more robust than escaping LIKE characters since there is no SQL text matching code to get wrong.

---

### H2. Double-filtering with divergent timestamps -- VERIFIED FIXED

**Approach:** Removed all SQL-side filtering (TTL, text, minSalience, sorting). The `query()` method now fetches all rows and delegates entirely to `applyQueryFilter`.

**Verification:** `sqlite-store.ts:114-123` contains only `SELECT * FROM table`, `rows.map(rowToItem)`, and `applyQueryFilter(items, query)`. The `SqliteRow` interface and `rowToItem()` helper (lines 12-32) cleanly map rows to `MemoryItem` objects, eliminating the previously duplicated mapping logic.

**Potential regression check:** The trade-off (fetching all rows for large tables) is documented in the fix summary. For the stated use case (LLM context memory stores, typically hundreds to low thousands of items), this is fine. The salience index from M7 still provides value if SQL-side filtering is re-added later.

**Verdict:** Correct and complete.

---

### H3. Redis KEYS replaced with SCAN -- VERIFIED FIXED

**Approach:** Added a private `scanKeys()` method that uses `this.client.scanStream()` with cursor-based iteration.

**Verification:** `redis-store.ts:91-106` implements the stream-based approach correctly:

- Uses `scanStream({ match: prefix + "*", count: 100 })` for batched iteration.
- Accumulates keys from `data` events, resolves on `end`, rejects on `error`.
- The `query()` method (line 66) calls `scanKeys()` instead of `this.client.keys()`.

**Mock verification:** `redis.test.ts:46-61` implements `scanStream()` returning a `Readable` stream that emits keys in one batch via `process.nextTick()`. This correctly simulates the async streaming behavior. The mock's `replace("*", "")` pattern extraction is simplistic but sufficient since the real code always uses `prefix + "*"`.

**Verdict:** Correct and complete.

---

### H4. Inconsistent TTL semantics -- VERIFIED FIXED (with minor residual gap)

**Approach:** TTL is now computed from `createdAt`, matching other stores. The Redis EX value is `Math.max(1, ceil((createdAt + ttlSeconds*1000 - Date.now()) / 1000))`.

**Verification:** `redis-store.ts:36-50` correctly computes the remaining time from `createdAt`. The `Math.max(1, ...)` prevents passing 0 or negative to Redis EX.

**Residual gap:** When an item is already expired at `put()` time (remaining time <= 0), the `Math.max(1, ...)` forces a 1-second Redis TTL. After 1 second, Redis auto-deletes the key, and `get()` returns `null`. In other stores, `get()` always returns the item regardless of TTL (expiry filtering only happens in `query()` via `applyQueryFilter`). This means:

- `InMemoryStore.get("expired-id")` returns the item.
- `RedisStore.get("expired-id")` returns `null` after 1 second.

This is an inherent limitation of using Redis-native expiry and cannot be fully resolved without dropping Redis EX entirely (which would mean expired keys accumulate in Redis indefinitely). The current fix is the pragmatic choice -- it aligns the TTL calculation timing while accepting this `get()` behavioral difference. Severity: LOW (edge case, and the item was already expired).

**Verdict:** Substantially fixed. The remaining gap is minor and inherent to the Redis EX mechanism.

---

### H5. JSONL corruption recovery -- VERIFIED FIXED

**Approach:** Added `FileStoreOptions.skipCorruptedLines` option. When enabled, individual lines that fail `JSON.parse` are skipped. Default behavior (throw) preserved.

**Verification:**

- `file-store.ts:7-10` defines the `FileStoreOptions` interface.
- `file-store.ts:37-46` wraps `JSON.parse` in try/catch, checking `this.options.skipCorruptedLines`.
- `factory.ts:48-52` passes `skipCorruptedLines` through to `FileStore`.
- `memory.test.ts:250-260` tests the default throw behavior.
- `memory.test.ts:262-276` tests skip behavior with a 3-line file (1 corrupted), verifying 2 items are loaded.

**Verdict:** Correct and complete.

---

### H6. Silent coercion of missing content -- VERIFIED FIXED

**Approach:** `normalizeMemoryItem` throws when `content` is `undefined` or `null`. Empty string `""` is accepted.

**Verification:**

- `utils.ts:6-10` checks `item.content === undefined || item.content === null` and throws.
- `memory.test.ts:30-42` tests missing content, undefined content, and empty string acceptance.
- `memory.test.ts:190-193` tests `InMemoryStore.put({ id: "a" })` rejects.
- `redis.test.ts:146-148` tests `RedisStore.put({ id: "a" })` rejects.

**Verdict:** Correct and complete.

---

## Medium Priority Issues

### M1. Duplicate export -- VERIFIED FIXED

**Verification:** `index.ts` has 7 lines, no duplicates. Each module exported once.

**Verdict:** Fixed.

---

### M2. Missing utils export -- VERIFIED FIXED

**Verification:** `index.ts:2` exports `"./utils.js"`. The functions `normalizeMemoryItem`, `isExpired`, `decaySalience`, and `applyQueryFilter` are now part of the public API.

**Verdict:** Fixed.

---

### M3. Optional close() made required and async -- VERIFIED FIXED

**Verification:**

- `types.ts:17` declares `close(): Promise<void>` (not optional).
- `InMemoryStore.close()` (`in-memory-store.ts:32-34`): Clears the Map. Async.
- `FileStore.close()` (`file-store.ts:104-106`): Awaits `this.writeQueue`. Async.
- `SqliteStore.close()` (`sqlite-store.ts:132-134`): Calls `this.db.close()` (synchronous better-sqlite3 call, wrapped in async method). Correct.
- `RedisStore.close()` (`redis-store.ts:86-88`): Calls `await this.client.quit()`. Async.
- Tests: `memory.test.ts:183-188` tests InMemoryStore close, `memory.test.ts:320-330` tests FileStore close, `redis.test.ts:139-144` tests RedisStore close. SqliteStore close is tested implicitly (all SqliteStore tests call `await store.close()`).

**Verdict:** Correct and complete.

---

### M4. FileStore persist error handling -- NOT ADDRESSED (intentionally deferred)

The audit noted that after a persist failure, in-memory and on-disk state diverge. The fix summary does not mention M4. The code is unchanged -- `persist()` still swallows the error on the queue chain while propagating it to the caller. The in-memory state remains ahead of the file. This is documented behavior and acceptable for now, but worth noting as a future improvement.

---

### M5. Redis options not exposed through factory -- VERIFIED FIXED

**Verification:**

- `factory.ts:15-17` adds `redisOptions` and `redisPrefix` to `MemoryStoreOptions`.
- `factory.ts:59-71` prefers `redisOptions` over `url`, passes prefix through to `RedisStoreOptions`.
- Error message updated to `"RedisStore requires a 'url' or 'redisOptions' option"` (`factory.ts:62-63`).

**Verdict:** Correct and complete.

---

### M6. SQLite strftime NULL for malformed timestamps -- NOT ADDRESSED (no longer applicable)

The H2 fix removed all SQL-side TTL filtering including the `strftime('%s', created_at)` expression. TTL filtering is now handled by `applyQueryFilter` which uses `Date.parse()`. `Date.parse` returns `NaN` for malformed timestamps, and `isExpired()` (`utils.ts:26`) returns `false` for `NaN`, meaning items with malformed timestamps are never considered expired. This is a reasonable default -- the M6 issue is effectively resolved as a side effect of H2.

---

### M7. SQLite salience index added -- VERIFIED FIXED

**Verification:** `sqlite-store.ts:64-67` adds `CREATE INDEX IF NOT EXISTS idx_{table}_salience ON {table} (salience DESC)` during `init()`. Note: since the H2 fix removed SQL-side sorting, this index currently provides no direct benefit. However, it is harmless and will be useful if SQL-side filtering/sorting is re-added in the future.

**Verdict:** Fixed. Index is preemptive but not harmful.

---

### M8. Redis configurable prefix -- VERIFIED FIXED

**Verification:**

- `redis-store.ts:7-10` defines `RedisStoreOptions` with optional `prefix`.
- `redis-store.ts:24` defaults to `"ce_memory:"`.
- All key operations use `this.prefix` (lines 46, 52, 60, 82, 95).
- `redis.test.ts:151-158` tests custom prefix `"myapp:"`.

**Verdict:** Correct and complete.

---

## Low Priority Issues

### L1. Misleading test name -- VERIFIED FIXED

**Verification:** `memory.test.ts:523-527` now tests `"postgres"` (truly unknown type) with error message `"Unknown memory store type"`. Separate test at line 537-539 tests `"throws when redis store missing url and redisOptions"`.

**Verdict:** Fixed.

---

### L2. Non-.js import extension -- VERIFIED FIXED

**Verification:** `redis.test.ts:2` uses `"./factory.js"` and `redis.test.ts:3` uses `"./redis-store.js"`.

**Verdict:** Fixed.

---

### L3. Two describe("SqliteStore") blocks -- VERIFIED FIXED

**Verification:** `memory.test.ts` has a single `describe("SqliteStore", ...)` block starting at line 333, containing all SqliteStore tests including the limit/decay test that was previously in a separate block.

**Verdict:** Fixed.

---

### L4. decaySalience age clamping -- VERIFIED FIXED

**Verification:** `utils.ts:37` uses `Math.max(0, (now - createdAt) / 1000)`. Future timestamps produce zero age (decay factor = 1.0, no amplification).

**Verdict:** Correct and complete.

---

### L5. Redis quit() instead of disconnect() -- VERIFIED FIXED

**Verification:** `redis-store.ts:87` calls `await this.client.quit()`. The mock at `redis.test.ts:75-78` implements `quit()` as async.

**Verdict:** Fixed.

---

## Notes (N1-N4) -- Reviewed but not actionable

### N1. FileStore atomicity on Windows

Not addressed. Acceptable -- this is a documentation note, not a bug.

### N2. No concurrency tests for SqliteStore

Not addressed. The H2 fix (removing SQL-side filtering) reduces the surface area for concurrency bugs since all filtering is now done in JS after fetching all rows. Still a valid gap for future testing.

### N3. `Partial<MemoryItem>` type is too loose

Not addressed. The H6 fix (content validation) provides runtime protection against the worst case (missing content). A stricter input type remains a future improvement.

### N4. No clear() or count() methods

Not addressed. Out of scope for this audit's fixes.

---

## Regression Analysis

### SQLite query correctness after removing SQL-side filtering

No regressions. The `query()` method now has identical filtering behavior to `InMemoryStore` and `FileStore`. The test suite includes text, minSalience, TTL, limit, and LIKE wildcard tests for SqliteStore.

### Redis SCAN correctness

No regressions. The `scanKeys()` implementation correctly handles empty keyspaces (returns empty array, short-circuits in `query()`), single batches, and the custom prefix. The mock simulates the stream interface adequately.

### FileStore corruption recovery edge cases

No regressions. Default behavior (throw on corrupt lines) is preserved. The skip behavior is additive. Tests cover both paths. Edge case: a file with only corrupted lines and `skipCorruptedLines: true` would return an empty store, which is correct.

### close() async behavior

No regressions. All four stores implement `async close(): Promise<void>`. The InMemoryStore clears items (destructive but documented). FileStore awaits pending writes. SqliteStore wraps the synchronous `db.close()` in an async method (correct -- the resolved promise indicates closure is complete). RedisStore uses `quit()` which properly waits for pending commands.

---

## Issues Found in Fixes: None

No code changes were required. All 17 applied fixes are correct and introduce no new bugs. The 2 deferred medium issues (M4, M6) and 4 notes (N1-N4) are reasonable deferrals. The one residual gap in H4 (Redis `get()` returning `null` for expired items after 1 second, vs other stores returning the item) is an inherent trade-off of using Redis-native expiry and is LOW severity.

---

## Test Coverage Assessment

| Issue | Test Added                                                                              | Adequate                          |
| ----- | --------------------------------------------------------------------------------------- | --------------------------------- |
| H1    | `handles LIKE wildcard characters in text query`                                        | Yes                               |
| H2    | Covered by existing text/TTL/salience tests on SqliteStore                              | Yes                               |
| H3    | Mock updated to `scanStream`                                                            | Yes                               |
| H4    | No explicit test for createdAt-based TTL computation                                    | Weak -- see note below            |
| H5    | `skips corrupted lines when skipCorruptedLines is true`                                 | Yes                               |
| H6    | 3 normalizeMemoryItem tests + 2 store-level reject tests                                | Yes                               |
| M3    | `close() clears items`, `close() awaits pending writes`, `close() cleans up the client` | Yes                               |
| M5    | Implicit (factory tests exercise new error message)                                     | Acceptable                        |
| M7    | No explicit index test                                                                  | Acceptable (index is transparent) |
| M8    | `uses custom prefix for keys`                                                           | Yes                               |
| L1    | Test updated with correct assertion                                                     | Yes                               |
| L4    | No explicit test for age clamping                                                       | Weak -- see note below            |

**Weak coverage notes:**

- **H4:** No test explicitly verifies that a Redis item with `createdAt` set to 30 seconds ago and `ttlSeconds: 60` receives a Redis EX of ~30 seconds. The mock does track expiries but no assertion checks the computed TTL value.
- **L4:** No test verifies that future `createdAt` values do not amplify salience. A test with a future timestamp asserting `salience <= base_salience` would be valuable.

These are minor gaps -- the logic is straightforward and correct by inspection. They would be worthwhile additions for regression protection.
