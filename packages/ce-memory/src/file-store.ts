import type { MemoryItem } from "@context-engineering/core";
import { promises as fs } from "fs";
import path from "path";
import type { MemoryQuery, MemoryStore } from "./types.js";
import { applyQueryFilter, normalizeMemoryItem } from "./utils.js";

export interface FileStoreOptions {
  /** When true, skip lines that fail JSON.parse instead of throwing. */
  skipCorruptedLines?: boolean;
  /** Maximum time in ms to wait for the advisory file lock (default 5000). */
  lockTimeout?: number;
  /** Age in ms after which an existing lock file is considered stale (default 10000). */
  staleLockAge?: number;
  /** When true, skip advisory file locking entirely (default false). */
  disableLocking?: boolean;
}

export class FileStore implements MemoryStore {
  private filePath: string;
  private options: FileStoreOptions;
  private items = new Map<string, MemoryItem>();
  private writeQueue: Promise<void> = Promise.resolve();
  private loadPromise: Promise<void> | null = null;
  private closed = false;

  constructor(filePath: string, options: FileStoreOptions = {}) {
    this.filePath = filePath;
    this.options = options;
  }

  private assertOpen(): void {
    if (this.closed) {
      throw new Error("FileStore is closed");
    }
  }

  private ensureLoaded(): Promise<void> {
    this.assertOpen();
    if (!this.loadPromise) {
      this.loadPromise = this.doLoad();
    }
    return this.loadPromise;
  }

  private async doLoad(): Promise<void> {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    await this.reloadFromDisk();
  }

  /**
   * Re-read the current on-disk file and replace this.items with fresh state,
   * bypassing the loadPromise memoization. Builds a new Map and only assigns it
   * on success, so a corrupt line (when skipCorruptedLines is false) throws
   * without clobbering the existing in-memory state.
   */
  private async reloadFromDisk(): Promise<void> {
    const items = new Map<string, MemoryItem>();

    try {
      const content = await fs.readFile(this.filePath, "utf-8");
      const lines = content.split(/\r?\n/).filter(l => l.trim());
      for (const line of lines) {
        try {
          const item = JSON.parse(line) as MemoryItem;
          items.set(item.id, item);
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

    this.items = items;
  }

  private get lockPath(): string {
    return this.filePath + ".lock";
  }

  private async withFileLock<T>(fn: () => Promise<T>): Promise<T> {
    if (this.options.disableLocking) {
      return fn();
    }

    const lockTimeout = this.options.lockTimeout ?? 5000;
    const staleLockAge = this.options.staleLockAge ?? 10000;
    const lockContent = JSON.stringify({
      pid: process.pid,
      timestamp: new Date().toISOString(),
    });

    const deadline = Date.now() + lockTimeout;
    let delay = 50;

    while (true) {
      try {
        const handle = await fs.open(this.lockPath, "wx");
        try {
          await handle.writeFile(lockContent);
        } catch (writeErr) {
          // We created this lock with "wx"; remove the orphan so it does not
          // linger as a non-stale lock blocking the next writer for staleLockAge.
          await fs.unlink(this.lockPath).catch(() => {});
          throw writeErr;
        } finally {
          await handle.close().catch(() => {});
        }
        break;
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code !== "EEXIST") {
          throw err;
        }

        // Check for stale lock
        try {
          const stat = await fs.stat(this.lockPath);
          if (Date.now() - stat.mtimeMs > staleLockAge) {
            await fs.unlink(this.lockPath);
            continue; // Retry immediately after removing stale lock
          }
        } catch (statErr) {
          if ((statErr as NodeJS.ErrnoException).code === "ENOENT") {
            continue; // Lock was removed by another process, retry
          }
          throw statErr;
        }

        if (Date.now() >= deadline) {
          const lockErr = new Error(
            `Failed to acquire file lock on ${this.lockPath} within ${lockTimeout}ms`
          );
          (lockErr as unknown as { cause: unknown }).cause = err;
          throw lockErr;
        }

        await new Promise<void>(resolve => setTimeout(resolve, delay));
        delay = Math.min(delay * 2, deadline - Date.now());
      }
    }

    try {
      return await fn();
    } finally {
      try {
        await fs.unlink(this.lockPath);
      } catch {
        // Lock file may have been cleaned up externally; ignore
      }
    }
  }

  private persistWithMutation(mutation: () => void): Promise<void> {
    // Serialize writes through a queue to prevent concurrent .tmp file races.
    // Mutation is applied inside the queue so in-memory state only changes
    // after a successful write. On failure, we roll back.
    const write = this.writeQueue.then(async () => {
      const snapshot = new Map(this.items);
      try {
        await this.withFileLock(async () => {
          // Re-read the current on-disk state inside the lock so writes
          // committed by other processes/instances since we loaded are not
          // clobbered (atomic read-modify-write). The mutation closures are
          // pure deltas (put = set, forget = delete), so re-applying them on
          // freshly-read state is correct.
          await this.reloadFromDisk();
          mutation();
          const lines = Array.from(this.items.values()).map(item =>
            JSON.stringify(item)
          );
          const content = lines.join("\n") + (lines.length ? "\n" : "");
          // Atomic write: write to temp file, then rename.
          const tmpPath = this.filePath + ".tmp";
          await fs.writeFile(tmpPath, content);
          await fs.rename(tmpPath, this.filePath);
        });
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
    if (this.closed) return;
    await this.writeQueue;
    this.items.clear();
    this.loadPromise = null;
    this.closed = true;
  }
}
