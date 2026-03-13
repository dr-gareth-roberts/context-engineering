import { Redis } from "ioredis";
import type { MemoryItem } from "@context-engineering/core";
import type { MemoryStore, MemoryQuery } from "./types.js";
import { normalizeMemoryItem, applyQueryFilter } from "./utils.js";

export class RedisStore implements MemoryStore {
  private client: Redis;

  constructor(urlOrOptions: string | any) {
    this.client = new Redis(urlOrOptions);
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
        pipeline.set(`ce_memory:${e.id}`, data, "EX", e.ttlSeconds);
      } else {
        pipeline.set(`ce_memory:${e.id}`, data);
      }
    }
    await pipeline.exec();
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    const data = await this.client.get(`ce_memory:${id}`);
    if (!data) return null;
    
    const item: MemoryItem = JSON.parse(data);
    
    // Update last access TTL if applicable
    if (item.ttlSeconds) {
      await this.client.set(`ce_memory:${id}`, JSON.stringify(item), "EX", item.ttlSeconds);
    }
    return item;
  }

  async query(query?: MemoryQuery): Promise<MemoryItem[]> {
    const keys = await this.client.keys("ce_memory:*");
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
    const result = await this.client.del(`ce_memory:${id}`);
    return result > 0;
  }

  close(): void {
    this.client.disconnect();
  }
}
