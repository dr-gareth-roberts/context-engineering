import type { MemoryStore } from "./types";
import { InMemoryStore } from "./in-memory-store";
import { FileStore } from "./file-store";
import { SqliteStore } from "./sqlite-store";

interface MemoryStoreOptions {
  path?: string;
  tableName?: string;
}

/**
 * Create a memory store by type name.
 *
 * @param type - The store type: "memory", "file", or "sqlite"
 * @param options - Store-specific options (path required for file/sqlite)
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
  type: "memory" | "file" | "sqlite",
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
    default:
      throw new Error(`Unknown memory store type: ${type}`);
  }
}
