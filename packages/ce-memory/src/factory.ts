import type { RedisOptions } from "ioredis";
import type { MemoryStore } from "./types.js";
import { InMemoryStore } from "./in-memory-store.js";
import { FileStore } from "./file-store.js";
import type { FileStoreOptions } from "./file-store.js";
import { SqliteStore } from "./sqlite-store.js";
import { RedisStore } from "./redis-store.js";
import type { RedisStoreOptions } from "./redis-store.js";

export interface MemoryStoreOptions {
  path?: string;
  tableName?: string;
  url?: string;
  /** ioredis connection options (alternative to url for Redis). */
  redisOptions?: RedisOptions;
  /** Redis key prefix. Defaults to "ce_memory:". */
  redisPrefix?: string;
  /** FileStore: skip corrupted JSONL lines instead of throwing. */
  skipCorruptedLines?: boolean;
}

/**
 * Create a memory store by type name.
 *
 * @param type - The store type: "memory", "file", "sqlite", or "redis"
 * @param options - Store-specific options (path required for file/sqlite, url or redisOptions for redis)
 * @returns A MemoryStore instance
 * @throws {Error} If type is unknown or required options are missing
 *
 * @example
 * ```ts
 * const store = createMemoryStore("sqlite", { path: "data.db" });
 * await store.put({ id: "1", content: "Hello" });
 * ```
 */
export function createMemoryStore(
  type: "memory" | "file" | "sqlite" | "redis",
  options: MemoryStoreOptions = {}
): MemoryStore {
  switch (type) {
    case "memory":
      return new InMemoryStore();
    case "file":
      if (!options.path) {
        throw new Error("FileStore requires a 'path' option");
      }
      {
        const fileOpts: FileStoreOptions = {};
        if (options.skipCorruptedLines !== undefined) {
          fileOpts.skipCorruptedLines = options.skipCorruptedLines;
        }
        return new FileStore(options.path, fileOpts);
      }
    case "sqlite":
      if (!options.path) {
        throw new Error("SqliteStore requires a 'path' option");
      }
      return new SqliteStore(options.path, { tableName: options.tableName });
    case "redis": {
      const connectionArg = options.redisOptions ?? options.url;
      if (!connectionArg) {
        throw new Error("RedisStore requires a 'url' or 'redisOptions' option");
      }
      const storeOpts: RedisStoreOptions = {};
      if (options.redisPrefix !== undefined) {
        storeOpts.prefix = options.redisPrefix;
      }
      return new RedisStore(connectionArg, storeOpts);
    }
    default:
      throw new Error(`Unknown memory store type: ${type}`);
  }
}
