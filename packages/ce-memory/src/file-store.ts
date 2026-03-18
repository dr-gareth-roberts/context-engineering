import type { MemoryItem } from "@context-engineering/core";
import { promises as fs } from "fs";
import path from "path";
import type { MemoryQuery, MemoryStore } from "./types.js";
import { applyQueryFilter, normalizeMemoryItem } from "./utils.js";

export interface FileStoreOptions {
  /** When true, skip lines that fail JSON.parse instead of throwing. */
  skipCorruptedLines?: boolean;
}

export class FileStore implements MemoryStore {
  private filePath: string;
  private options: FileStoreOptions;
  private items = new Map<string, MemoryItem>();
  private writeQueue: Promise<void> = Promise.resolve();
  private loadPromise: Promise<void> | null = null;
  constructor(filePath: string, options: FileStoreOptions = {}) {
    this.filePath = filePath;
    this.options = options;
  }

  private ensureLoaded(): Promise<void> {
    if (!this.loadPromise) {
      this.loadPromise = this.doLoad();
    }
    return this.loadPromise;
  }

  private async doLoad(): Promise<void> {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });

    try {
      const content = await fs.readFile(this.filePath, "utf-8");
      const lines = content.split(/\r?\n/).filter(l => l.trim());
      for (const line of lines) {
        try {
          const item = JSON.parse(line) as MemoryItem;
          this.items.set(item.id, item);
        } catch (parseError) {
          if (!this.options.skipCorruptedLines) {
            throw parseError;
          }
          // Silently skip corrupted lines when opted in
        }
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }

  private persistWithMutation(mutation: () => void): Promise<void> {
    // Serialize writes through a queue to prevent concurrent .tmp file races.
    // Mutation is applied inside the queue so in-memory state only changes
    // after a successful write. On failure, we roll back.
    const write = this.writeQueue.then(async () => {
      const snapshot = new Map(this.items);
      mutation();
      try {
        const lines = Array.from(this.items.values()).map(item =>
          JSON.stringify(item)
        );
        const content = lines.join("\n") + (lines.length ? "\n" : "");
        // Atomic write: write to temp file, then rename.
        const tmpPath = this.filePath + ".tmp";
        await fs.writeFile(tmpPath, content);
        await fs.rename(tmpPath, this.filePath);
      } catch (error) {
        // Roll back in-memory state to match what's on disk
        this.items = snapshot;
        throw error;
      }
    });
    // Keep the queue alive even if this write fails
    this.writeQueue = write.catch(() => {});
    return write;
  }

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    await this.ensureLoaded();
    const list = Array.isArray(item) ? item : [item];
    const normalized = list.map(entry => normalizeMemoryItem(entry));
    await this.persistWithMutation(() => {
      for (const entry of normalized) {
        this.items.set(entry.id, entry);
      }
    });
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
    let existed = false;
    await this.persistWithMutation(() => {
      existed = this.items.has(id);
      if (existed) {
        this.items.delete(id);
      }
    });
    return existed;
  }

  async close(): Promise<void> {
    await this.writeQueue;
  }
}
