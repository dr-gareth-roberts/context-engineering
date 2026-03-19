import type { MemoryItem } from "@context-engineering/core";
import type { MemoryQuery, MemoryStore } from "./types.js";
import { applyQueryFilter, normalizeMemoryItem } from "./utils.js";

export class InMemoryStore implements MemoryStore {
  private items = new Map<string, MemoryItem>();
  private closed = false;

  private assertOpen(): void {
    if (this.closed) {
      throw new Error("InMemoryStore is closed");
    }
  }

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    this.assertOpen();
    const list = Array.isArray(item) ? item : [item];
    const normalized = list.map(entry => normalizeMemoryItem(entry));
    for (const entry of normalized) {
      this.items.set(entry.id, entry);
    }
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    this.assertOpen();
    return this.items.get(id) ?? null;
  }

  async query(query: MemoryQuery = {}): Promise<MemoryItem[]> {
    this.assertOpen();
    const values = Array.from(this.items.values());
    return applyQueryFilter(values, query);
  }

  async forget(id: string): Promise<boolean> {
    this.assertOpen();
    return this.items.delete(id);
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.items.clear();
  }
}
