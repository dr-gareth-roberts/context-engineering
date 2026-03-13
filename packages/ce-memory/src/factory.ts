import type { MemoryStore } from "./types.js";
import { InMemoryStore } from "./in-memory-store.js";
import { FileStore } from "./file-store.js";
import { SqliteStore } from "./sqlite-store.js";
import { RedisStore } from "./redis-store.js";

interface MemoryStoreOptions {
  path?: string;
  tableName?: string;
  url?: string;
}

/**
 * Create a memory store by type name.
 *
 * @param type - The store type: "memory", "file", "sqlite", or "redis"
 * @param options - Store-specific options (path required for file/sqlite, url for redis)
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
      return new FileStore(options.path);
    case "sqlite":
      if (!options.path) {
        throw new Error("SqliteStore requires a 'path' option");
      }
      return new SqliteStore(options.path, { tableName: options.tableName });
    case "redis":
      if (!options.url) {
        throw new Error("RedisStore requires a 'url' option");
      }
      return new RedisStore(options.url);
    default:
      throw new Error(`Unknown memory store type: ${type}`);
  }
}
