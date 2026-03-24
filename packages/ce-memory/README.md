# @context-engineering/memory

Pluggable memory stores (in-memory, JSONL file, SQLite) for context engineering agents.

## Installation

```bash
npm install @context-engineering/memory
```

Includes `@context-engineering/core`, `better-sqlite3`, and `ioredis` as dependencies. Redis support requires the `ioredis` package (included as a dependency).

## Quick Start

```ts
import { createMemoryStore } from "@context-engineering/memory";

const store = createMemoryStore("sqlite", { path: "./memory.db" });

await store.put({ content: "The user prefers dark mode" });
const items = await store.query({ minSalience: 0.5, limit: 10 });
```

## Store Types

| Type       | Class           | Persistence     | Notes                                                                                                                                                                                                           |
| ---------- | --------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `'memory'` | `InMemoryStore` | None            | Fast, ephemeral                                                                                                                                                                                                 |
| `'file'`   | `FileStore`     | JSONL file      | Requires `path` option, advisory file locking. Options: `lockTimeout` (lock timeout in ms), `staleLockAge` (age in ms after which a lock is considered stale), `disableLocking` (disable advisory file locking) |
| `'sqlite'` | `SqliteStore`   | SQLite database | Requires `path` option, supports `tableName`                                                                                                                                                                    |
| `'redis'`  | `RedisStore`    | Redis           | Requires `url` or `redisOptions`. Supports `prefix` option for namespacing keys in shared Redis instances (also available as `redisPrefix` in the factory)                                                      |

Use `createMemoryStore(type, options?)` or instantiate classes directly.

## MemoryStore Interface

```ts
interface MemoryStore {
  put(item: Partial<MemoryItem> | Partial<MemoryItem>[]): Promise<MemoryItem[]>;
  get(id: string): Promise<MemoryItem | null>;
  query(query?: MemoryQuery): Promise<MemoryItem[]>;
  forget(id: string): Promise<boolean>;
  close(): Promise<void>; // all stores throw on operations after close()
}
```

Items are auto-normalised on `put`: missing `id` gets a nanoid, `createdAt`/`updatedAt` default to now, `salience` defaults to 1.

## Query Options

| Field             | Type      | Description                                                                                                                                                                        |
| ----------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text`            | `string`  | Substring match on content (case-insensitive)                                                                                                                                      |
| `limit`           | `number`  | Max items to return                                                                                                                                                                |
| `minSalience`     | `number`  | Filter by minimum salience score                                                                                                                                                   |
| `includeExpired`  | `boolean` | Include items past their TTL                                                                                                                                                       |
| `halfLifeSeconds` | `number`  | Decay half-life in seconds. When provided, results are sorted by decayed salience. When omitted, no decay is applied. (The `decaySalience()` utility uses 30 days as its default.) |
| `now`             | `number`  | Override current timestamp for TTL and decay calculations (default: current time)                                                                                                  |

Results are sorted by salience (descending).

## Utilities

| Export                                | Description                              |
| ------------------------------------- | ---------------------------------------- |
| `normalizeMemoryItem(partial)`        | Fill defaults for a partial `MemoryItem` |
| `isExpired(item, now)`                | Check if an item has exceeded its TTL    |
| `decaySalience(item, now, halfLife?)` | Compute decayed salience score           |
| `applyQueryFilter(items, query)`      | Apply query filters to an item array     |

## License

MIT
