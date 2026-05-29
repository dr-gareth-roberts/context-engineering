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
    this.records = await this.readDiskRecords();
  }

  /**
   * Read the current on-disk records as a fresh array.
   * Returns an empty array when the file does not yet exist.
   */
  private async readDiskRecords(): Promise<FeedbackRecord[]> {
    try {
      const content = await fs.readFile(this.filePath, "utf-8");
      const lines = content.split(/\r?\n/).filter(l => l.trim());
      return lines.map(line => JSON.parse(line) as FeedbackRecord);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return [];
      }
      throw error;
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
        // Read-merge-write under the lock so a concurrent process that has
        // already advanced the file is not silently overwritten. The lock only
        // prevents torn writes; without re-reading here, two processes that both
        // loaded the same snapshot would each rewrite the whole file from their
        // own in-memory list, dropping each other's records (lost updates).
        const onDisk = await this.readDiskRecords();
        this.records = mergeRecordLists(onDisk, this.records);
        await this.writeRecords(this.records);
      });
    });
    this.writeQueue = write.catch(() => {});
    return write;
  }

  /** Atomically write records to disk via a temp file + rename. */
  private async writeRecords(records: FeedbackRecord[]): Promise<void> {
    const lines = records.map(r => JSON.stringify(r));
    const content = lines.join("\n") + (lines.length ? "\n" : "");
    const tmpPath = this.filePath + ".tmp";
    await fs.writeFile(tmpPath, content);
    await fs.rename(tmpPath, this.filePath);
  }

  async save(record: FeedbackRecord): Promise<void> {
    await this.ensureLoaded();
    this.records.push(structuredClone(record));
    await this.persist();
  }

  async updateOutcome(packId: string, outcome: Outcome): Promise<void> {
    await this.ensureLoaded();

    // Re-read on-disk records under the lock before searching so an outcome can
    // be attached to a record created by another process (which would not be in
    // this instance's in-memory list). Without this, a long-lived optimizer can
    // never report outcomes for packs produced by a sibling worker.
    const write = this.writeQueue.then(async () => {
      await this.withFileLock(async () => {
        const onDisk = await this.readDiskRecords();
        this.records = mergeRecordLists(onDisk, this.records);
        const record = this.records.find(r => r.packId === packId);
        if (!record) {
          return;
        }
        record.outcome = outcome;
        await this.writeRecords(this.records);
      });
    });
    this.writeQueue = write.catch(() => {});
    await write;
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

    // clear() is an intentional removal, so it must NOT go through the
    // read-merge-write path in persist() (which would resurrect just-cleared
    // records from disk). Instead read the current on-disk state under the lock,
    // drop the targeted records there too, and write the result directly.
    const write = this.writeQueue.then(async () => {
      await this.withFileLock(async () => {
        const onDisk = await this.readDiskRecords();
        const filtered =
          segment !== undefined
            ? onDisk.filter(r => r.segment !== segment)
            : [];
        this.records =
          segment !== undefined
            ? this.records.filter(r => r.segment !== segment)
            : [];
        await this.writeRecords(filtered);
      });
    });
    this.writeQueue = write.catch(() => {});
    await write;
  }
}

/**
 * Merge two record lists keyed by id so concurrent writers do not lose each
 * other's updates. On-disk records come first to preserve append order; records
 * only present in `mine` are appended in their existing order.
 *
 * Conflict resolution for a shared id: prefer the copy that carries an outcome
 * (an attached outcome is newer information than a record without one). When
 * both copies have an outcome, prefer `mine` because it is the version this
 * write is actively producing (last-writer-wins for the active mutation).
 */
function mergeRecordLists(
  onDisk: FeedbackRecord[],
  mine: FeedbackRecord[]
): FeedbackRecord[] {
  const byId = new Map<string, FeedbackRecord>();

  for (const record of onDisk) {
    byId.set(record.id, record);
  }

  for (const record of mine) {
    const existing = byId.get(record.id);
    if (existing === undefined) {
      byId.set(record.id, record);
      continue;
    }
    byId.set(record.id, pickPreferred(existing, record));
  }

  // Preserve on-disk order first, then any ids only present in `mine`.
  const ordered: FeedbackRecord[] = [];
  const seen = new Set<string>();
  for (const record of onDisk) {
    ordered.push(byId.get(record.id)!);
    seen.add(record.id);
  }
  for (const record of mine) {
    if (!seen.has(record.id)) {
      ordered.push(byId.get(record.id)!);
      seen.add(record.id);
    }
  }
  return ordered;
}

/**
 * Choose between an on-disk record and the in-memory (`mine`) record for the
 * same id. Prefers whichever carries an outcome; `mine` wins ties.
 */
function pickPreferred(
  onDisk: FeedbackRecord,
  mine: FeedbackRecord
): FeedbackRecord {
  const onDiskHasOutcome = onDisk.outcome !== undefined;
  const mineHasOutcome = mine.outcome !== undefined;

  if (mineHasOutcome) return mine;
  if (onDiskHasOutcome) return onDisk;
  return mine;
}
