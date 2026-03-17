import { Redis } from "ioredis";
import type { RedisOptions } from "ioredis";
import type { MemoryItem } from "@context-engineering/core";
import type { MemoryStore, MemoryQuery } from "./types.js";
import { normalizeMemoryItem, applyQueryFilter } from "./utils.js";

export interface RedisStoreOptions {
  /** Key prefix for all items. Defaults to "ce_memory:". */
  prefix?: string;
}

export class RedisStore implements MemoryStore {
  private client: Redis;
  private prefix: string;

  constructor(
    urlOrOptions: string | RedisOptions,
    storeOptions: RedisStoreOptions = {}
  ) {
    this.client =
      typeof urlOrOptions === "string"
        ? new Redis(urlOrOptions)
        : new Redis(urlOrOptions);
    this.prefix = storeOptions.prefix ?? "ce_memory:";
  }

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    const items = Array.isArray(item) ? item : [item];
    const normalized = items.map(normalizeMemoryItem);

    const pipeline = this.client.pipeline();
    for (const e of normalized) {
      const data = JSON.stringify(e);
      if (e.ttlSeconds !== undefined && e.ttlSeconds > 0) {
        // Compute effective TTL from createdAt, consistent with other stores.
        // TTL is the remaining time from now until createdAt + ttlSeconds.
        const createdMs = Date.parse(e.createdAt);
        const expiresMs = createdMs + e.ttlSeconds * 1000;
        const remainingSeconds = Math.max(
          1,
          Math.ceil((expiresMs - Date.now()) / 1000)
        );
        pipeline.set(`${this.prefix}${e.id}`, data, "EX", remainingSeconds);
      } else {
        pipeline.set(`${this.prefix}${e.id}`, data);
      }
    }
    await pipeline.exec();
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    const data = await this.client.get(`${this.prefix}${id}`);
    if (!data) return null;
    return JSON.parse(data) as MemoryItem;
  }

  async query(query?: MemoryQuery): Promise<MemoryItem[]> {
    const keys = await this.scanKeys();
    if (keys.length === 0) return [];

    const values = await this.client.mget(keys);
    const items: MemoryItem[] = [];

    for (const data of values) {
      if (data) {
        items.push(JSON.parse(data) as MemoryItem);
      }
    }

    return applyQueryFilter(items, query || {});
  }

  async forget(id: string): Promise<boolean> {
    const result = await this.client.del(`${this.prefix}${id}`);
    return result > 0;
  }

  async close(): Promise<void> {
    await this.client.quit();
  }

  /** Use SCAN-based iteration instead of KEYS to avoid blocking Redis. */
  private scanKeys(): Promise<string[]> {
    return new Promise<string[]>((resolve, reject) => {
      const keys: string[] = [];
      const stream = this.client.scanStream({
        match: `${this.prefix}*`,
        count: 100,
      });
      stream.on("data", (batch: string[]) => {
        for (const key of batch) {
          keys.push(key);
        }
      });
      stream.on("end", () => resolve(keys));
      stream.on("error", (err: Error) => reject(err));
    });
  }
}
