import type { MemoryItem } from "@ce/core";
import type { MemoryQuery, MemoryStore } from "./types.js";
import { applyQueryFilter, normalizeMemoryItem } from "./utils.js";

export class InMemoryStore implements MemoryStore {
  private items = new Map<string, MemoryItem>();

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    const list = Array.isArray(item) ? item : [item];
    const normalized = list.map(entry => normalizeMemoryItem(entry));
    for (const entry of normalized) {
      this.items.set(entry.id, entry);
    }
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    return this.items.get(id) ?? null;
  }

  async query(query: MemoryQuery = {}): Promise<MemoryItem[]> {
    const values = Array.from(this.items.values());
    return applyQueryFilter(values, query);
  }

  async forget(id: string): Promise<boolean> {
    return this.items.delete(id);
  }
}
