# @context-engineering/memory

Pluggable memory stores (in-memory, JSONL file, SQLite) for context engineering agents.

## Installation

```bash
npm install @context-engineering/memory
```

Requires `@context-engineering/core` as a peer. The SQLite store uses `better-sqlite3` (included).

## Quick Start

```ts
import { createMemoryStore } from "@context-engineering/memory";

const store = createMemoryStore("sqlite", { path: "./memory.db" });

await store.put({ content: "The user prefers dark mode" });
const items = await store.query({ minSalience: 0.5, limit: 10 });
```

## Store Types

| Type       | Class           | Persistence     | Notes                                        |
| ---------- | --------------- | --------------- | -------------------------------------------- |
| `'memory'` | `InMemoryStore` | None            | Fast, ephemeral                              |
| `'file'`   | `FileStore`     | JSONL file      | Requires `path` option, advisory file locking |
| `'sqlite'` | `SqliteStore`   | SQLite database | Requires `path` option, supports `tableName` |
| `'redis'`  | `RedisStore`    | Redis           | Requires `url` or `redisOptions`             |

Use `createMemoryStore(type, options?)` or instantiate classes directly.

## MemoryStore Interface

```ts
interface MemoryStore {
  put(item: Partial<MemoryItem> | Partial<MemoryItem>[]): Promise<MemoryItem[]>;
  get(id: string): Promise<MemoryItem | null>;
  query(query?: MemoryQuery): Promise<MemoryItem[]>;
  forget(id: string): Promise<boolean>;
  close(): Promise<void>;  // all stores throw on operations after close()
}
```

Items are auto-normalized on `put`: missing `id` gets a nanoid, `createdAt`/`updatedAt` default to now, `salience` defaults to 1.

## Query Options

| Field             | Type      | Description                                         |
| ----------------- | --------- | --------------------------------------------------- |
| `text`            | `string`  | Substring match on content (case-insensitive)       |
| `limit`           | `number`  | Max items to return                                 |
| `minSalience`     | `number`  | Filter by minimum salience score                    |
| `includeExpired`  | `boolean` | Include items past their TTL                        |
| `halfLifeSeconds` | `number`  | Apply exponential salience decay (default: 30 days) |

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
