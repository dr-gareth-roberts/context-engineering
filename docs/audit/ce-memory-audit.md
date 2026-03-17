# ce-memory Deep Audit

**Date:** 2026-03-17
**Scope:** `packages/ce-memory/src/` -- all 8 source files and 2 test files
**Auditor:** Claude Opus 4.6 (automated)

## Summary

The `ce-memory` package implements four memory store backends (InMemory, File, SQLite, Redis) behind a clean `MemoryStore` interface. The InMemoryStore is solid. The FileStore has a well-designed write queue for atomicity. The SqliteStore validates table names against injection. However, there are several **high**-priority bugs (SQLite LIKE injection, double-filtering producing wrong results, Redis `KEYS` in production), multiple **medium** issues (duplicate export, missing `utils` export, inconsistent `close()` semantics, no corruption recovery), and various lower-priority items.

**Issue counts:** 0 Critical, 6 High, 8 Medium, 5 Low, 4 Notes

---

## Critical Issues

None.

---

## High Priority

### H1. SQLite `LIKE` injection via unescaped `query.text`

**File:** `src/sqlite-store.ts:123-124`
**Severity:** HIGH

```ts
conditions.push("content LIKE ?");
params.push(`%${query.text}%`);
```

SQLite `LIKE` has wildcard characters `%` and `_`. If `query.text` contains these characters (e.g., `"%"` or `"_secret_"`), they are interpolated as wildcards, not literals. This means:

- `query.text = "%"` matches every row (the SQL becomes `LIKE '%%%'` which is `LIKE '%'`).
- `query.text = "a_b"` matches `"aXb"`, `"a1b"`, etc.

This is not SQL _injection_ (parameterized queries prevent that), but it is a **semantic correctness bug** -- the LIKE filter does not match the JS-side `includes()` behavior in `applyQueryFilter`. The JS side does exact substring matching; the SQL side does LIKE pattern matching.

**Impact:** Query results differ between SqliteStore and InMemoryStore/FileStore for any text containing `%` or `_`. The double-filtering (see H2) partially masks this since `applyQueryFilter` re-checks, but the SQL LIKE may exclude rows that the JS filter would have kept (e.g., if the LIKE pattern is more restrictive due to `_` wildcards).

**Fix:** Escape `%` and `_` in the query text before inserting into the LIKE pattern:

```ts
const escaped = query.text.replace(/[%_]/g, ch => `\\${ch}`);
conditions.push("content LIKE ? ESCAPE '\\'");
params.push(`%${escaped}%`);
```

---

### H2. SqliteStore `query()` double-filters, causing incorrect results

**File:** `src/sqlite-store.ts:108-165`
**Severity:** HIGH

The method pushes filters into SQL (TTL expiry, text LIKE, minSalience) then calls `applyQueryFilter(items, query)` on the result set. This means every filter runs twice. The problems:

1. **TTL double-check with different `now` values.** SQL uses `query.now ?? Date.now()` at line 114, but `applyQueryFilter` computes its own `Date.now()` at line 41 of utils.ts. These calls are separated by the time it takes to execute the SQL query and map rows. In edge cases, an item could pass the SQL TTL check but fail the JS TTL check (or vice versa) because `now` advanced between the two checks.

2. **Text filter case sensitivity mismatch.** SQLite `LIKE` is case-insensitive for ASCII by default, but the JS `applyQueryFilter` uses `.toLowerCase().includes()` which is case-insensitive for all Unicode. For ASCII content this matches, but for non-ASCII (e.g., Turkish "I") behavior could diverge.

3. **minSalience applied twice when `halfLifeSeconds` is undefined.** The SQL pushes `salience >= ?` and then `applyQueryFilter` re-applies the same filter. This is wasteful but not incorrect.

4. **Sorting applied twice.** SQL sorts by `salience DESC`, then `applyQueryFilter` re-sorts by (possibly decayed) salience. The second sort is the authoritative one, making the SQL sort wasted work.

**Impact:** Subtle correctness bugs around TTL boundary conditions. Performance overhead from redundant filtering and sorting on every query.

**Fix:** Either:

- (A) Remove all SQL-side filtering and let `applyQueryFilter` handle everything (simpler, correct, slightly less efficient for large datasets).
- (B) Keep SQL filtering but pass the same `now` timestamp to both layers, and skip `applyQueryFilter` for the filters already applied in SQL. This requires refactoring `applyQueryFilter` to accept flags for which filters to skip.

---

### H3. Redis `KEYS` command used in `query()` -- production performance hazard

**File:** `src/redis-store.ts:43`
**Severity:** HIGH

```ts
const keys = await this.client.keys("ce_memory:*");
```

The Redis `KEYS` command scans the entire keyspace and blocks the server. From the Redis documentation: "KEYS should only be used in production environments with extreme care." For any non-trivial dataset (thousands of keys), this will cause latency spikes. In a shared Redis instance, it affects all clients.

**Impact:** `query()` becomes a production hazard as the dataset grows. Any call to `query()` blocks the Redis server for the duration of the scan.

**Fix:** Use `SCAN` with cursor-based iteration:

```ts
async query(query?: MemoryQuery): Promise<MemoryItem[]> {
  const items: MemoryItem[] = [];
  let cursor = '0';
  do {
    const [nextCursor, keys] = await this.client.scan(
      cursor, 'MATCH', 'ce_memory:*', 'COUNT', 100
    );
    cursor = nextCursor;
    if (keys.length > 0) {
      const values = await this.client.mget(keys);
      for (const data of values) {
        if (data) items.push(JSON.parse(data) as MemoryItem);
      }
    }
  } while (cursor !== '0');
  return applyQueryFilter(items, query || {});
}
```

---

### H4. Redis TTL semantics differ from other stores

**File:** `src/redis-store.ts:26-27`
**Severity:** HIGH

```ts
if (e.ttlSeconds !== undefined && e.ttlSeconds > 0) {
  pipeline.set(`ce_memory:${e.id}`, data, "EX", e.ttlSeconds);
}
```

The TTL is calculated from the time of the `put()` call, not from `createdAt`. In every other store, TTL expiry is computed as `createdAt + ttlSeconds`. This means:

- If you `put()` an item with `createdAt` set to 1 hour ago and `ttlSeconds: 3600`, InMemoryStore/FileStore/SqliteStore will consider it expired immediately, but RedisStore will keep it alive for another 3600 seconds.
- If you `put()` an item with a future `createdAt`, other stores extend the effective TTL, but Redis ignores `createdAt` entirely.

Additionally, when Redis expires a key, the item disappears from `get()` as well, but in other stores `get()` always returns the item regardless of TTL (only `query()` filters expired items by default).

**Impact:** TTL behavior is inconsistent across store implementations. Code that works correctly with InMemoryStore will behave differently with RedisStore.

**Fix:** Either:

- Store the computed expiry correctly: `const effectiveTtl = Math.max(0, Math.floor((Date.parse(e.createdAt) + e.ttlSeconds * 1000 - Date.now()) / 1000))` and use that as the Redis EX value.
- Or store items without Redis EX and handle TTL in the application layer (like other stores do via `applyQueryFilter`), accepting that Redis won't auto-clean expired keys.

---

### H5. FileStore does not handle corrupted JSONL lines gracefully

**File:** `src/file-store.ts:30-31`
**Severity:** HIGH

```ts
for (const line of lines) {
  const item = JSON.parse(line) as MemoryItem;
```

If any line in the JSONL file is corrupted (partial write due to crash, disk error, manual editing), `JSON.parse` throws and the entire store becomes unusable. All items, including valid ones before and after the corrupt line, are lost.

The test at `memory.test.ts:222-233` explicitly verifies this behavior ("Should throw on corrupted JSON -- FileStore doesn't skip bad lines"), indicating this is intentional. However, for a file-based store that claims atomic writes, corruption from external factors (OS crash mid-rename, disk errors) or manual editing is a realistic scenario.

**Impact:** A single corrupted byte in the file makes the entire store unloadable. All data is effectively lost until manually repaired.

**Fix:** Add a `skipCorruptedLines` option (default `false` for backward compatibility) that logs a warning and skips unparseable lines:

```ts
for (const line of lines) {
  try {
    const item = JSON.parse(line) as MemoryItem;
    this.items.set(item.id, item);
  } catch (e) {
    if (this.options?.skipCorruptedLines) {
      console.warn(`Skipping corrupted line in ${this.filePath}: ${e}`);
    } else {
      throw e;
    }
  }
}
```

---

### H6. `normalizeMemoryItem` silently coerces missing `content` to empty string

**File:** `src/utils.ts:9`
**Severity:** HIGH

```ts
content: item.content ?? "",
```

When `put()` is called with `{}` (no content), it silently creates an item with `content: ""`. This is likely a data entry error that should be caught early. Every store allows inserting empty-content items without any warning. Combined with auto-generated IDs (line 8), you can call `store.put({})` and get back a valid-looking item with no meaningful data.

**Impact:** Silent data quality issues. Callers who forget to set `content` get no feedback.

**Fix:** Either validate that `content` is a non-empty string, or at minimum that `content` is provided (not `undefined`). Throw a `ValidationError` for missing content.

---

## Medium Priority

### M1. Duplicate `export * from "./types.js"` in index.ts

**File:** `src/index.ts:1-2`
**Severity:** MEDIUM

```ts
export * from "./types.js";
export * from "./types.js";
```

Line 1 and line 2 are identical. While this does not cause a runtime error (duplicate re-exports are silently merged), it indicates copy-paste sloppiness and could confuse tooling or linters.

**Fix:** Remove the duplicate line.

---

### M2. `utils.ts` is not exported from `index.ts`

**File:** `src/index.ts`
**Severity:** MEDIUM

The barrel file exports types, all four stores, and the factory, but **not** `utils.ts`. This means `normalizeMemoryItem`, `isExpired`, `decaySalience`, and `applyQueryFilter` are not part of the public API.

If these are intentionally internal, that is fine but should be documented. However, `applyQueryFilter` and `decaySalience` are potentially useful for consumers building custom stores, and `toContextItem` in `ce-core/bridge.ts` already expects consumers to work with `MemoryItem` objects directly.

**Fix:** Either export the utility functions or add a `@internal` JSDoc tag to clarify they are not public.

---

### M3. `close()` is optional on the interface but required for resource cleanup

**File:** `src/types.ts:17`
**Severity:** MEDIUM

```ts
close?(): void;
```

`close()` is optional (`?`), which means:

1. Code that receives a `MemoryStore` cannot call `store.close()` without a null check or type narrowing.
2. `InMemoryStore` and `FileStore` do not implement `close()` at all. While InMemoryStore truly needs no cleanup, FileStore has a pending `writeQueue` that could have unfinished writes when the process exits.

**Impact:** Callers using the `MemoryStore` interface cannot write `store.close()` -- they must write `store.close?.()`. FileStore has no way to flush pending writes or signal completion.

**Fix:**

- Make `close()` required on the interface (return `void` or `Promise<void>`).
- Add a no-op `close()` to InMemoryStore.
- Add a `close()` to FileStore that awaits the write queue:
  ```ts
  async close(): Promise<void> {
    await this.writeQueue;
  }
  ```
- Change the interface return type to `Promise<void>` since SqliteStore and RedisStore have synchronous close but FileStore needs async.

---

### M4. FileStore `persist()` silently swallows errors on the queue chain

**File:** `src/file-store.ts:56`
**Severity:** MEDIUM

```ts
this.writeQueue = write.catch(() => {});
```

The comment explains this prevents a failed write from "poisoning" the queue. However, the original `write` promise (returned to the caller via `persist()`) does propagate the error. The issue is that if `put()` or `forget()` does not `await` the returned promise properly (they do currently), or if a future refactor breaks this, write failures would be silently lost.

More importantly, after a failed persist, the in-memory state and the on-disk state are out of sync. The in-memory Map has the new data, but the file does not. Subsequent reads from a fresh FileStore instance will see stale data.

**Impact:** After a persist failure, in-memory and on-disk state diverge silently. The next successful persist will overwrite the file with the current in-memory state, which includes the "failed" write's data, so the data is not actually lost -- but the caller was told (via the rejected promise) that the write failed.

**Fix:** Consider either:

- Reverting the in-memory change on persist failure (true transactional behavior).
- Or documenting that a persist failure is non-fatal and the data will be written on the next successful persist.

---

### M5. RedisStore constructor signature differs from factory

**File:** `src/redis-store.ts:10`, `src/factory.ts:48`
**Severity:** MEDIUM

```ts
// redis-store.ts
constructor(urlOrOptions: string | RedisOptions)

// factory.ts
return new RedisStore(options.url);
```

`RedisStore` accepts either a URL string or a full `RedisOptions` object, but the factory only exposes `url: string`. There is no way to pass Redis options (password, TLS, db number, sentinels, etc.) through the factory.

**Impact:** Users who need Redis authentication, TLS, or clustering cannot use the factory and must instantiate `RedisStore` directly, defeating the purpose of the factory abstraction.

**Fix:** Extend `MemoryStoreOptions` to accept `redisOptions?: RedisOptions` and pass it through, or accept `url | RedisOptions` in the factory.

---

### M6. SQLite `strftime('%s', created_at)` may return `NULL` for malformed timestamps

**File:** `src/sqlite-store.ts:116`
**Severity:** MEDIUM

```ts
"(ttl_seconds IS NULL OR (CAST(strftime('%s', created_at) AS INTEGER) * 1000 + ttl_seconds * 1000) > ?)";
```

`strftime('%s', created_at)` requires `created_at` to be a valid SQLite datetime string. The `normalizeMemoryItem` function generates ISO 8601 timestamps like `"2025-01-15T10:30:00.123Z"`. SQLite's `strftime` accepts ISO 8601 with the `T` separator and optional fractional seconds, so this generally works.

However, if `created_at` is malformed (e.g., set directly via SQL or migrated from another system), `strftime` returns `NULL`, and `CAST(NULL AS INTEGER)` is `NULL`, and `NULL * 1000` is `NULL`, and `NULL > ?` is `NULL` (falsy). This means items with malformed timestamps are silently excluded from query results.

**Impact:** Items with non-ISO-8601 `created_at` values are invisible to TTL-filtered queries.

**Fix:** Add a fallback or validate timestamps on insert. The current `normalizeMemoryItem` provides a safe default, so this is only an issue for items inserted through other means.

---

### M7. No index on `salience` or `content` columns in SQLite

**File:** `src/sqlite-store.ts:30-41`
**Severity:** MEDIUM

The CREATE TABLE statement creates only a PRIMARY KEY index on `id`. Queries that filter by `salience` or search `content` with LIKE will do full table scans. The ORDER BY `salience DESC` also requires a sort step without an index.

**Impact:** Query performance degrades linearly with table size. For stores with thousands of items, queries become slow.

**Fix:** Add indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_{table}_salience ON {table} (salience DESC);
```

A `content` index would not help LIKE queries with leading `%`, so full-text search (FTS5) would be needed for text queries at scale.

---

### M8. Redis key prefix `ce_memory:` is hardcoded and not configurable

**File:** `src/redis-store.ts:27-29`
**Severity:** MEDIUM

The prefix `ce_memory:` is hardcoded in every method. If multiple applications share a Redis instance, or if a single application needs multiple independent memory stores, key collisions are inevitable.

**Impact:** Cannot run multiple independent RedisStore instances on the same Redis server.

**Fix:** Accept an optional `prefix` in the constructor:

```ts
constructor(urlOrOptions: string | RedisOptions, options?: { prefix?: string }) {
  this.prefix = options?.prefix ?? "ce_memory:";
  // ...
}
```

---

## Low Priority

### L1. Test file `memory.test.ts:443-444` has misleading test name

**File:** `src/memory.test.ts:443-444`
**Severity:** LOW

```ts
it("throws for unknown type", () => {
  expect(() => createMemoryStore("redis" as any)).toThrow();
});
```

The test description says "throws for unknown type" but `"redis"` is a valid type. The test passes because `url` is not provided (so the factory throws "RedisStore requires a 'url' option"). The test is accidentally correct but for the wrong reason. If someone adds a default URL, this test would fail despite the feature working correctly.

**Fix:** Either:

- Change to a truly unknown type: `createMemoryStore("postgres" as any)`
- Or rename the test: `"throws when redis store missing url"` (and it already has a separate test for sqlite missing path at line 451).

---

### L2. `redis.test.ts:2` uses non-`.js` import extension

**File:** `src/redis.test.ts:2`
**Severity:** LOW

```ts
import { createMemoryStore } from "./factory";
```

All other imports in the codebase use `.js` extensions for ESM compatibility (e.g., `"./factory.js"`). This works in the test environment because Vitest handles it, but it is inconsistent with the rest of the codebase.

**Fix:** Change to `"./factory.js"` for consistency.

---

### L3. Two separate `describe("SqliteStore")` blocks in `memory.test.ts`

**File:** `src/memory.test.ts:279, 317`
**Severity:** LOW

There are two `describe("SqliteStore", ...)` blocks. The first (line 279) tests `applies limit after JS-side decay filtering`. The second (line 317) tests all the standard operations. These should be merged into a single describe block for readability and conventional test organization.

**Fix:** Move the test at line 280-314 into the second describe block.

---

### L4. `decaySalience` returns potentially negative salience for future `createdAt`

**File:** `src/utils.ts:32-34`
**Severity:** LOW

```ts
const ageSeconds = (now - createdAt) / 1000;
const decayFactor = Math.exp((-Math.LN2 * ageSeconds) / halfLifeSeconds);
return (item.salience ?? 1) * decayFactor;
```

If `createdAt` is in the future (e.g., due to clock skew), `ageSeconds` is negative, making `decayFactor > 1`. This _amplifies_ salience rather than decaying it. An item created "1 hour from now" would have a higher effective salience than its base value.

**Impact:** Items with future timestamps sort higher than expected. This is an edge case but could be exploited or cause confusion.

**Fix:** Clamp `ageSeconds` to non-negative: `const ageSeconds = Math.max(0, (now - createdAt) / 1000);`

---

### L5. `RedisStore.close()` calls `disconnect()` which does not wait for pending commands

**File:** `src/redis-store.ts:63-65`
**Severity:** LOW

```ts
close(): void {
  this.client.disconnect();
}
```

`ioredis` `disconnect()` forcefully closes the connection without waiting for pending commands. If there is a `put()` in flight (pipeline executing), it will fail silently. The safer alternative is `this.client.quit()` which sends the QUIT command and waits for pending replies, but it returns a Promise (which conflicts with the `void` return type).

**Impact:** Calling `close()` immediately after `put()` may lose data.

**Fix:** Change to `quit()` and make `close()` async:

```ts
async close(): Promise<void> {
  await this.client.quit();
}
```

---

## Notes & Questions

### N1. FileStore atomicity guarantee depends on `rename()` being atomic

The atomic write pattern (write to `.tmp`, then `rename`) is correct on POSIX systems where `rename()` is atomic. On Windows, `rename()` can fail if the destination exists (Node.js `fs.rename` uses `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING` which is atomic on NTFS). This is fine for the stated `node >= 18` engine requirement but worth noting.

### N2. No concurrency tests for SqliteStore

The SqliteStore uses WAL mode, which supports concurrent reads. However, there are no tests for concurrent writes or reads-during-writes. SQLite handles this internally with locks, but testing would verify the WAL setup works correctly.

### N3. `MemoryStore.put()` accepts `Partial<MemoryItem>` which is extremely loose

The type `Partial<MemoryItem>` means every field is optional, including `id` and `content`. While `normalizeMemoryItem` fills in defaults, this means the type system provides no guidance to callers about what they should provide. A stricter type like `{ content: string } & Partial<Omit<MemoryItem, 'content'>>` would be more helpful.

### N4. No `clear()` or `count()` methods on the interface

The `MemoryStore` interface has `put`, `get`, `query`, `forget`, and `close`. Common operations like `clear()` (delete all items) and `count()` (get item count) are missing. These are easy to add: InMemoryStore would use `this.items.clear()`, SqliteStore would use `DELETE FROM table`, Redis would use `DEL` on all matched keys, etc.

---

## Good Patterns

1. **Write queue in FileStore** (`src/file-store.ts:41-57`). The promise-chaining pattern for serializing writes is elegant and prevents concurrent `.tmp` file races without locks. The `.catch(() => {})` to prevent queue poisoning is a thoughtful detail.

2. **SQL injection prevention in SqliteStore** (`src/sqlite-store.ts:18-22`). Table name validation with a strict regex prevents injection through user-controlled table names. All query parameters use proper parameterized queries.

3. **Lazy loading in FileStore** (`src/file-store.ts:17-22`). The `ensureLoaded()` pattern with a cached promise avoids redundant reads and handles the "first call" problem cleanly.

4. **Shared `applyQueryFilter` utility** (`src/utils.ts:37-71`). Centralizing filter logic ensures consistent behavior across stores. The decay salience calculation is mathematically sound (exponential decay with configurable half-life).

5. **Factory pattern with validation** (`src/factory.ts`). Required options are validated eagerly with clear error messages. The union type on the `type` parameter provides compile-time safety.

6. **WAL mode for SQLite** (`src/sqlite-store.ts:25`). Enabling WAL journal mode is the correct choice for concurrent read access.

7. **Batch operations with transactions** (`src/sqlite-store.ts:61-73`). Wrapping batch inserts in a transaction is correct for both performance and atomicity.

---

## File-by-File Detail

### `src/types.ts` (18 lines)

Clean and minimal. Defines `MemoryQuery` and `MemoryStore` interfaces. One issue:

- **M3**: `close?(): void` should be required and possibly async.
- **N3**: `put()` signature accepts `Partial<MemoryItem>` which is too loose.

### `src/index.ts` (7 lines)

Barrel file with two issues:

- **M1**: Duplicate `export * from "./types.js"` on lines 1-2.
- **M2**: Does not export `utils.ts`.

### `src/utils.ts` (71 lines)

Core utility functions. Well-structured. Issues:

- **H6**: `normalizeMemoryItem` silently coerces missing content to `""`.
- **L4**: `decaySalience` amplifies salience for future `createdAt` values.

### `src/factory.ts` (52 lines)

Factory function with good validation. Issues:

- **M5**: Cannot pass Redis options (auth, TLS) through the factory.

### `src/in-memory-store.ts` (31 lines)

Simplest implementation. Clean and correct. No issues beyond those inherited from the interface (M3, N3).

### `src/file-store.ts` (89 lines)

File-backed store with atomic writes. Well-designed overall. Issues:

- **H5**: No recovery from corrupted JSONL lines.
- **M4**: Persist errors leave in-memory/on-disk state out of sync.
- No `close()` method to await pending writes.

### `src/sqlite-store.ts` (177 lines)

Most complex store. Uses parameterized queries and transactions. Issues:

- **H1**: LIKE wildcards in `query.text` not escaped.
- **H2**: Double-filtering with potentially different `now` values.
- **M6**: `strftime` returns NULL for malformed timestamps.
- **M7**: No secondary indexes for query performance.

### `src/redis-store.ts` (66 lines)

Redis-backed store. Functional but with significant concerns:

- **H3**: Uses `KEYS` command (blocks Redis server).
- **H4**: TTL semantics differ from other stores.
- **M8**: Hardcoded key prefix.
- **L5**: `disconnect()` does not wait for pending commands.

### `src/memory.test.ts` (454 lines)

Comprehensive tests for InMemoryStore, FileStore, SqliteStore, and factory. Issues:

- **L1**: Misleading test name "throws for unknown type" at line 443.
- **L3**: Two separate `describe("SqliteStore")` blocks.
- Missing tests: no concurrent access tests for SqliteStore, no test for LIKE wildcard behavior, no test for `close()` on stores that implement it, no test for FileStore persist failure recovery.

### `src/redis.test.ts` (112 lines)

Redis tests using a mock. Covers edge cases (empty array, missing item, negative TTL, empty query). Issues:

- **L2**: Non-`.js` import extension.
- The mock does not simulate `KEYS` blocking behavior, so the H3 issue is not observable in tests.
- No test for `close()` followed by operations.
- Mock `keys()` pattern matching is simplified (`pattern.replace("*", "")`) and would not handle complex glob patterns, though this is acceptable for a mock.
