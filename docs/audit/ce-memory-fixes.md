# ce-memory Audit Fixes

**Date:** 2026-03-17
**Scope:** All fixes from the ce-memory deep audit
**Files modified:** 8 source files, 2 test files

---

## High Priority Fixes

### H1. SQLite LIKE wildcard injection -- Fixed

**File:** `src/sqlite-store.ts`
**Resolution:** Eliminated entirely by H2's fix. The SqliteStore `query()` method no longer constructs SQL LIKE clauses. All text filtering is handled by `applyQueryFilter` which uses `String.includes()` -- a literal substring match with no wildcard interpretation.

**New test:** `"handles LIKE wildcard characters in text query"` in `memory.test.ts` verifies that `%` and `_` in query text are treated as literals.

---

### H2. Double-filtering with divergent timestamps -- Fixed

**File:** `src/sqlite-store.ts` (lines 114-124)
**Resolution:** Removed all SQL-side filtering (TTL, text LIKE, minSalience). The `query()` method now fetches all rows with a simple `SELECT * FROM table` and delegates all filtering to `applyQueryFilter`. This:

- Eliminates the double-filtering bug where SQL and JS used different `now` values
- Eliminates the case-sensitivity mismatch between LIKE and `includes()`
- Eliminates redundant sorting
- Ensures SqliteStore behavior is identical to InMemoryStore and FileStore

Extracted a shared `SqliteRow` interface and `rowToItem()` helper to deduplicate the row-to-MemoryItem mapping that was previously inlined in both `get()` and `query()`.

**Trade-off:** For very large SQLite tables (100k+ rows), fetching all rows into JS is less efficient than SQL-side filtering. This is acceptable for the current use case (memory stores for LLM context). If needed later, SQL-side filtering can be re-added with proper LIKE escaping and a shared `now` timestamp.

---

### H3. Redis KEYS blocking command -- Fixed

**File:** `src/redis-store.ts` (lines 90-106)
**Resolution:** Replaced `this.client.keys("ce_memory:*")` with a new `scanKeys()` private method that uses `this.client.scanStream()`. This returns a Readable stream that iterates the keyspace incrementally using the SCAN command, avoiding the server-blocking behavior of KEYS.

The `scanStream` call uses `{ match: prefix + "*", count: 100 }` for batched iteration.

**Mock updated:** The Redis mock in `redis.test.ts` now implements `scanStream()` returning a `Readable` stream that emits matching keys, replacing the old `keys()` mock.

---

### H4. Inconsistent TTL semantics across stores -- Fixed

**File:** `src/redis-store.ts` (lines 36-50)
**Resolution:** Redis TTL is now computed from `createdAt`, consistent with other stores. Instead of passing `ttlSeconds` directly as the Redis EX value, the code now computes:

```
remainingSeconds = Math.max(1, ceil((createdAt + ttlSeconds*1000 - Date.now()) / 1000))
```

This means an item created 30 seconds ago with `ttlSeconds: 60` gets a Redis EX of ~30 seconds (the remaining time), matching the behavior of InMemoryStore/FileStore/SqliteStore which expire at `createdAt + ttlSeconds`.

The `Math.max(1, ...)` ensures we never pass 0 or negative to Redis EX (which would be an error or immediate expiry).

---

### H5. No JSONL corruption recovery -- Fixed

**File:** `src/file-store.ts` (lines 7-10, 37-46)
**Resolution:** Added a `FileStoreOptions` interface with `skipCorruptedLines?: boolean`. When enabled, individual lines that fail `JSON.parse` are silently skipped instead of aborting the entire load. Default behavior (throw on corrupt lines) is preserved for backward compatibility.

The option is also exposed through the factory via `MemoryStoreOptions.skipCorruptedLines`.

**New test:** `"skips corrupted lines when skipCorruptedLines is true"` verifies that a file with one bad line among three loads the two valid items.

---

### H6. Silent coercion of missing content to empty string -- Fixed

**File:** `src/utils.ts` (lines 5-10)
**Resolution:** `normalizeMemoryItem` now throws `Error("MemoryItem requires a 'content' field")` when `content` is `undefined` or `null`. Empty string `""` is still accepted (it is a valid, if unusual, content value).

**New tests:**

- `"throws when content is missing"` -- `normalizeMemoryItem({})`
- `"throws when content is undefined"` -- `normalizeMemoryItem({ id: "a" })`
- `"accepts empty string content"` -- `normalizeMemoryItem({ content: "" })`
- `"rejects put without content"` -- on both InMemoryStore and RedisStore

---

## Medium Priority Fixes

### M1. Duplicate export in index.ts -- Fixed

**File:** `src/index.ts`
**Resolution:** Removed the duplicate `export * from "./types.js"` line.

---

### M2. Missing utils export -- Fixed

**File:** `src/index.ts`
**Resolution:** Added `export * from "./utils.js"`. This makes `normalizeMemoryItem`, `isExpired`, `decaySalience`, and `applyQueryFilter` part of the public API, useful for consumers building custom stores.

---

### M3. Optional `close()` on interface -- Fixed

**Files:** `src/types.ts`, `src/in-memory-store.ts`, `src/file-store.ts`, `src/sqlite-store.ts`, `src/redis-store.ts`
**Resolution:** Changed `close?(): void` to `close(): Promise<void>` on the `MemoryStore` interface. All four implementations now have a `close()` method:

- **InMemoryStore:** Clears the internal Map.
- **FileStore:** Awaits the write queue to ensure all pending writes complete.
- **SqliteStore:** Closes the database connection (was already present, now returns `Promise<void>`).
- **RedisStore:** Calls `this.client.quit()` (was `disconnect()`, see L5).

Callers can now always call `await store.close()` without optional chaining.

---

### M5. Redis options not exposed through factory -- Fixed

**File:** `src/factory.ts` (lines 10-20, 59-71)
**Resolution:** `MemoryStoreOptions` now includes:

- `redisOptions?: RedisOptions` -- full ioredis connection options (auth, TLS, sentinels, etc.)
- `redisPrefix?: string` -- key prefix, passed to `RedisStoreOptions`

The factory prefers `redisOptions` over `url` if both are provided. The error message now reads `"RedisStore requires a 'url' or 'redisOptions' option"`.

---

### M7. No index on salience column in SQLite -- Fixed

**File:** `src/sqlite-store.ts` (lines 63-67)
**Resolution:** Added `CREATE INDEX IF NOT EXISTS idx_{table}_salience ON {table} (salience DESC)` during `init()`. This improves query performance for salience-sorted reads.

---

### M8. Hardcoded Redis key prefix -- Fixed

**File:** `src/redis-store.ts` (lines 7-10, 16-24)
**Resolution:** Added `RedisStoreOptions.prefix` (defaults to `"ce_memory:"`). All key operations now use `this.prefix` instead of the hardcoded string. This allows multiple independent RedisStore instances on the same Redis server.

**New test:** `"uses custom prefix for keys"` verifies that a store with `{ prefix: "myapp:" }` works correctly.

---

## Low Priority Fixes

### L1. Misleading test name -- Fixed

**File:** `src/memory.test.ts`
**Resolution:** Changed `"throws for unknown type"` to `"throws for unknown type"` with the actual test value changed from `"redis"` to `"postgres"` (a truly unknown type), and added a separate `"throws when redis store missing url and redisOptions"` test.

---

### L2. Non-.js import extension in redis.test.ts -- Fixed

**File:** `src/redis.test.ts`
**Resolution:** Changed `import { createMemoryStore } from "./factory"` to `"./factory.js"` and `import { RedisStore } from "./redis-store"` to `"./redis-store.js"`.

---

### L3. Two separate describe("SqliteStore") blocks -- Fixed

**File:** `src/memory.test.ts`
**Resolution:** Merged both `describe("SqliteStore", ...)` blocks into a single block.

---

### L4. decaySalience amplifies for future createdAt -- Fixed

**File:** `src/utils.ts` (line 37)
**Resolution:** Added `Math.max(0, ...)` clamp on `ageSeconds` so future timestamps produce zero age (no decay, no amplification).

---

### L5. Redis disconnect() does not wait for pending commands -- Fixed

**File:** `src/redis-store.ts` (line 87)
**Resolution:** Changed `this.client.disconnect()` to `await this.client.quit()`. The `quit()` method sends the Redis QUIT command and waits for pending replies before closing the connection. The `close()` method is now `async` returning `Promise<void>`, consistent with the updated interface.

---

## Cleanup

### Unused import removed

**File:** `src/redis-store.ts`
Removed unused `isExpired` import that was left from the original code (TTL filtering is handled by `applyQueryFilter` internally).

### SqliteRow type extracted

**File:** `src/sqlite-store.ts`
Extracted `SqliteRow` interface and `rowToItem()` helper function, eliminating duplicated row-mapping logic between `get()` and `query()`.

---

## Summary of All Files Changed

| File                     | Changes                                                                |
| ------------------------ | ---------------------------------------------------------------------- |
| `src/types.ts`           | `close()` required, returns `Promise<void>`                            |
| `src/index.ts`           | Removed duplicate export, added utils export                           |
| `src/utils.ts`           | Content validation in normalize, age clamping in decay                 |
| `src/in-memory-store.ts` | Added `close()` method                                                 |
| `src/file-store.ts`      | Added `FileStoreOptions`, `skipCorruptedLines`, `close()`              |
| `src/sqlite-store.ts`    | Removed double-filtering, extracted row helper, added index            |
| `src/redis-store.ts`     | SCAN instead of KEYS, createdAt-based TTL, configurable prefix, quit() |
| `src/factory.ts`         | Redis options/prefix passthrough, FileStore options passthrough        |
| `src/memory.test.ts`     | New tests for H1/H5/H6/M3, fixed test names, merged describe blocks    |
| `src/redis.test.ts`      | Updated mock for scanStream/quit, fixed imports, new tests             |
