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
  private closed = false;

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

  private assertOpen(): void {
    if (this.closed) {
      throw new Error("RedisStore is closed");
    }
  }

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    this.assertOpen();
    const items = Array.isArray(item) ? item : [item];
    const normalized = items.map(normalizeMemoryItem);

    const pipeline = this.client.pipeline();
    for (const e of normalized) {
      const data = JSON.stringify(e);
      // TTL is stored in the JSON payload; applyQueryFilter handles expiry
      // at query time. No Redis EX — this avoids semantic mismatch between
      // Redis-level deletion and application-level TTL checks.
      pipeline.set(`${this.prefix}${e.id}`, data);
    }
    const results = await pipeline.exec();
    if (results) {
      for (const [err] of results) {
        if (err) {
          throw new Error(`Redis pipeline command failed: ${err.message}`);
        }
      }
    }
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    this.assertOpen();
    const data = await this.client.get(`${this.prefix}${id}`);
    if (!data) return null;
    return JSON.parse(data) as MemoryItem;
  }

  async query(query?: MemoryQuery): Promise<MemoryItem[]> {
    this.assertOpen();
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
    this.assertOpen();
    const result = await this.client.del(`${this.prefix}${id}`);
    return result > 0;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
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
