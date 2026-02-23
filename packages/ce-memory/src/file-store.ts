import type { MemoryItem } from "@ce/core";
import { promises as fs } from "fs";
import path from "path";
import type { MemoryQuery, MemoryStore } from "./types";
import { applyQueryFilter, normalizeMemoryItem } from "./utils";

export class FileStore implements MemoryStore {
  private filePath: string;
  private loaded = false;
  private items = new Map<string, MemoryItem>();

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  private async ensureLoaded() {
    if (this.loaded) return;
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });

    try {
      const content = await fs.readFile(this.filePath, "utf-8");
      const lines = content.split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        const item = JSON.parse(line) as MemoryItem;
        this.items.set(item.id, item);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }

    this.loaded = true;
  }

  private async persist() {
    const lines = Array.from(this.items.values()).map((item) =>
      JSON.stringify(item)
    );
    await fs.writeFile(this.filePath, lines.join("\n") + (lines.length ? "\n" : ""));
  }

  async put(item: Partial<MemoryItem> | Partial<MemoryItem>[]): Promise<MemoryItem[]> {
    await this.ensureLoaded();
    const list = Array.isArray(item) ? item : [item];
    const normalized = list.map((entry) => normalizeMemoryItem(entry));
    for (const entry of normalized) {
      this.items.set(entry.id, entry);
    }
    await this.persist();
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    await this.ensureLoaded();
    return this.items.get(id) ?? null;
  }

  async query(query: MemoryQuery = {}): Promise<MemoryItem[]> {
    await this.ensureLoaded();
    return applyQueryFilter(Array.from(this.items.values()), query);
  }

  async forget(id: string): Promise<boolean> {
    await this.ensureLoaded();
    const deleted = this.items.delete(id);
    await this.persist();
    return deleted;
  }
}
