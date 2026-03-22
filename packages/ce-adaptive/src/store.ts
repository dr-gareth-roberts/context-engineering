import { promises as fs } from "fs";
import path from "path";
import type { FeedbackRecord, FeedbackStore, Outcome } from "./types.js";

/**
 * In-memory feedback store for testing and development.
 * Data is lost when the process exits.
 */
export class InMemoryFeedbackStore implements FeedbackStore {
  private records: FeedbackRecord[] = [];

  async save(record: FeedbackRecord): Promise<void> {
    this.records.push(structuredClone(record));
  }

  async updateOutcome(packId: string, outcome: Outcome): Promise<void> {
    const record = this.records.find(r => r.packId === packId);
    if (record) {
      record.outcome = outcome;
    }
  }

  async getRecords(options?: {
    segment?: string;
    limit?: number;
    since?: number;
  }): Promise<FeedbackRecord[]> {
    let result = this.records;

    if (options?.segment !== undefined) {
      result = result.filter(r => r.segment === options.segment);
    }
    if (options?.since !== undefined) {
      const since = options.since;
      result = result.filter(r => r.timestamp >= (since ?? 0));
    }

    // Return newest first
    result = result.slice().sort((a, b) => b.timestamp - a.timestamp);

    if (options?.limit !== undefined) {
      result = result.slice(0, options.limit);
    }

    return result.map(r => structuredClone(r));
  }

  async getRecordsWithOutcomes(options?: {
    segment?: string;
    limit?: number;
  }): Promise<FeedbackRecord[]> {
    let result = this.records.filter(r => r.outcome !== undefined);

    if (options?.segment !== undefined) {
      result = result.filter(r => r.segment === options.segment);
    }

    result = result.slice().sort((a, b) => b.timestamp - a.timestamp);

    if (options?.limit !== undefined) {
      result = result.slice(0, options.limit);
    }

    return result.map(r => structuredClone(r));
  }

  async clear(segment?: string): Promise<void> {
    if (segment !== undefined) {
      this.records = this.records.filter(r => r.segment !== segment);
    } else {
      this.records = [];
    }
  }
}

export interface FileFeedbackStoreOptions {
  /** Maximum time in ms to wait for the advisory file lock (default 5000). */
  lockTimeout?: number;
  /** Age in ms after which an existing lock file is considered stale (default 10000). */
  staleLockAge?: number;
  /** When true, skip advisory file locking entirely (default false). */
  disableLocking?: boolean;
}

/**
 * File-backed feedback store for local development.
 * Uses JSON-lines format with advisory file locking.
 */
export class FileFeedbackStore implements FeedbackStore {
  private filePath: string;
  private options: FileFeedbackStoreOptions;
  private records: FeedbackRecord[] = [];
  private writeQueue: Promise<void> = Promise.resolve();
  private loadPromise: Promise<void> | null = null;

  constructor(filePath: string, options: FileFeedbackStoreOptions = {}) {
    this.filePath = filePath;
    this.options = options;
  }

  private get lockPath(): string {
    return this.filePath + ".lock";
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
        const record = JSON.parse(line) as FeedbackRecord;
        this.records.push(record);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
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
        await handle.writeFile(lockContent);
        await handle.close();
        break;
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code !== "EEXIST") {
          throw err;
        }

        try {
          const stat = await fs.stat(this.lockPath);
          if (Date.now() - stat.mtimeMs > staleLockAge) {
            await fs.unlink(this.lockPath);
            continue;
          }
        } catch (statErr) {
          if ((statErr as NodeJS.ErrnoException).code === "ENOENT") {
            continue;
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

  private persist(): Promise<void> {
    const write = this.writeQueue.then(async () => {
      await this.withFileLock(async () => {
        const lines = this.records.map(r => JSON.stringify(r));
        const content = lines.join("\n") + (lines.length ? "\n" : "");
        const tmpPath = this.filePath + ".tmp";
        await fs.writeFile(tmpPath, content);
        await fs.rename(tmpPath, this.filePath);
      });
    });
    this.writeQueue = write.catch(() => {});
    return write;
  }

  async save(record: FeedbackRecord): Promise<void> {
    await this.ensureLoaded();
    this.records.push(structuredClone(record));
    await this.persist();
  }

  async updateOutcome(packId: string, outcome: Outcome): Promise<void> {
    await this.ensureLoaded();
    const record = this.records.find(r => r.packId === packId);
    if (record) {
      record.outcome = outcome;
      await this.persist();
    }
  }

  async getRecords(options?: {
    segment?: string;
    limit?: number;
    since?: number;
  }): Promise<FeedbackRecord[]> {
    await this.ensureLoaded();
    let result = this.records;

    if (options?.segment !== undefined) {
      result = result.filter(r => r.segment === options.segment);
    }
    if (options?.since !== undefined) {
      const since = options.since;
      result = result.filter(r => r.timestamp >= (since ?? 0));
    }

    result = result.slice().sort((a, b) => b.timestamp - a.timestamp);

    if (options?.limit !== undefined) {
      result = result.slice(0, options.limit);
    }

    return result.map(r => structuredClone(r));
  }

  async getRecordsWithOutcomes(options?: {
    segment?: string;
    limit?: number;
  }): Promise<FeedbackRecord[]> {
    await this.ensureLoaded();
    let result = this.records.filter(r => r.outcome !== undefined);

    if (options?.segment !== undefined) {
      result = result.filter(r => r.segment === options.segment);
    }

    result = result.slice().sort((a, b) => b.timestamp - a.timestamp);

    if (options?.limit !== undefined) {
      result = result.slice(0, options.limit);
    }

    return result.map(r => structuredClone(r));
  }

  async clear(segment?: string): Promise<void> {
    await this.ensureLoaded();
    if (segment !== undefined) {
      this.records = this.records.filter(r => r.segment !== segment);
    } else {
      this.records = [];
    }
    await this.persist();
  }
}
