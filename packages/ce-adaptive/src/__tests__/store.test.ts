import { describe, it, expect, afterEach } from "vitest";
import { InMemoryFeedbackStore, FileFeedbackStore } from "../store.js";
import type { FeedbackRecord, Outcome } from "../types.js";
import { promises as fs } from "fs";
import path from "path";
import os from "os";

function makeRecord(overrides?: Partial<FeedbackRecord>): FeedbackRecord {
  return {
    id: `rec_${Math.random().toString(36).slice(2)}`,
    timestamp: Date.now(),
    packId: `pack_${Math.random().toString(36).slice(2)}`,
    segment: "default",
    selectedItemIds: ["item_1"],
    droppedItemIds: ["item_2"],
    itemFeatures: [
      {
        itemId: "item_1",
        kind: "code",
        priority: 5,
        recency: 3,
        salience: 2,
        relevance: 4,
        tokens: 100,
        selected: true,
      },
      {
        itemId: "item_2",
        kind: "docs",
        priority: 3,
        recency: 1,
        salience: 1,
        relevance: 2,
        tokens: 50,
        selected: false,
      },
    ],
    weightsUsed: { priority: 1, recency: 1, salience: 1, relevance: 1 },
    budget: 1000,
    utilization: 0.8,
    ...overrides,
  };
}

describe("InMemoryFeedbackStore", () => {
  it("saves and retrieves records", async () => {
    const store = new InMemoryFeedbackStore();
    const record = makeRecord();

    await store.save(record);
    const records = await store.getRecords();

    expect(records).toHaveLength(1);
    expect(records[0].id).toBe(record.id);
  });

  it("updates outcome on existing record", async () => {
    const store = new InMemoryFeedbackStore();
    const record = makeRecord();
    await store.save(record);

    const outcome: Outcome = { quality: 0.9, accepted: true };
    await store.updateOutcome(record.packId, outcome);

    const records = await store.getRecords();
    expect(records[0].outcome).toEqual(outcome);
  });

  it("does not throw when updating non-existent packId", async () => {
    const store = new InMemoryFeedbackStore();
    await expect(
      store.updateOutcome("nonexistent", { quality: 0.5 })
    ).resolves.toBeUndefined();
  });

  it("filters by segment", async () => {
    const store = new InMemoryFeedbackStore();
    await store.save(makeRecord({ segment: "a" }));
    await store.save(makeRecord({ segment: "b" }));
    await store.save(makeRecord({ segment: "a" }));

    const records = await store.getRecords({ segment: "a" });
    expect(records).toHaveLength(2);
    expect(records.every(r => r.segment === "a")).toBe(true);
  });

  it("filters by since timestamp", async () => {
    const store = new InMemoryFeedbackStore();
    await store.save(makeRecord({ timestamp: 1000 }));
    await store.save(makeRecord({ timestamp: 2000 }));
    await store.save(makeRecord({ timestamp: 3000 }));

    const records = await store.getRecords({ since: 2000 });
    expect(records).toHaveLength(2);
  });

  it("respects limit", async () => {
    const store = new InMemoryFeedbackStore();
    for (let i = 0; i < 10; i++) {
      await store.save(makeRecord());
    }

    const records = await store.getRecords({ limit: 3 });
    expect(records).toHaveLength(3);
  });

  it("getRecordsWithOutcomes only returns records with outcomes", async () => {
    const store = new InMemoryFeedbackStore();
    const r1 = makeRecord();
    const r2 = makeRecord();
    await store.save(r1);
    await store.save(r2);

    await store.updateOutcome(r1.packId, { quality: 0.7 });

    const records = await store.getRecordsWithOutcomes();
    expect(records).toHaveLength(1);
    expect(records[0].packId).toBe(r1.packId);
  });

  it("clears all records", async () => {
    const store = new InMemoryFeedbackStore();
    await store.save(makeRecord());
    await store.save(makeRecord());

    await store.clear();
    const records = await store.getRecords();
    expect(records).toHaveLength(0);
  });

  it("clears records by segment", async () => {
    const store = new InMemoryFeedbackStore();
    await store.save(makeRecord({ segment: "a" }));
    await store.save(makeRecord({ segment: "b" }));

    await store.clear("a");
    const records = await store.getRecords();
    expect(records).toHaveLength(1);
    expect(records[0].segment).toBe("b");
  });

  it("returns cloned records to prevent mutation", async () => {
    const store = new InMemoryFeedbackStore();
    const record = makeRecord();
    await store.save(record);

    const [retrieved] = await store.getRecords();
    retrieved.segment = "mutated";

    const [fresh] = await store.getRecords();
    expect(fresh.segment).toBe("default");
  });
});

describe("FileFeedbackStore", () => {
  const tmpDir = path.join(os.tmpdir(), "ce-adaptive-test");
  let storePath: string;

  afterEach(async () => {
    try {
      await fs.rm(tmpDir, { recursive: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  function createStore(): FileFeedbackStore {
    storePath = path.join(
      tmpDir,
      `test_${Math.random().toString(36).slice(2)}.jsonl`
    );
    return new FileFeedbackStore(storePath, { disableLocking: true });
  }

  it("saves and retrieves records", async () => {
    const store = createStore();
    const record = makeRecord();

    await store.save(record);
    const records = await store.getRecords();

    expect(records).toHaveLength(1);
    expect(records[0].id).toBe(record.id);
  });

  it("persists records to disk", async () => {
    const record = makeRecord();

    const store1 = createStore();
    await store1.save(record);

    // Create a new store pointing to the same file
    const store2 = new FileFeedbackStore(storePath, { disableLocking: true });
    const records = await store2.getRecords();

    expect(records).toHaveLength(1);
    expect(records[0].id).toBe(record.id);
  });

  it("updates outcome and persists", async () => {
    const store = createStore();
    const record = makeRecord();
    await store.save(record);

    await store.updateOutcome(record.packId, { quality: 0.85 });

    // Verify with fresh store
    const store2 = new FileFeedbackStore(storePath, { disableLocking: true });
    const records = await store2.getRecords();
    expect(records[0].outcome?.quality).toBe(0.85);
  });

  it("filters by segment", async () => {
    const store = createStore();
    await store.save(makeRecord({ segment: "x" }));
    await store.save(makeRecord({ segment: "y" }));

    const records = await store.getRecords({ segment: "x" });
    expect(records).toHaveLength(1);
    expect(records[0].segment).toBe("x");
  });

  it("clears all records", async () => {
    const store = createStore();
    await store.save(makeRecord());
    await store.save(makeRecord());

    await store.clear();

    const records = await store.getRecords();
    expect(records).toHaveLength(0);
  });

  it("clears records by segment", async () => {
    const store = createStore();
    await store.save(makeRecord({ segment: "keep" }));
    await store.save(makeRecord({ segment: "remove" }));

    await store.clear("remove");

    const records = await store.getRecords();
    expect(records).toHaveLength(1);
    expect(records[0].segment).toBe("keep");
  });

  it("getRecordsWithOutcomes only returns records with outcomes", async () => {
    const store = createStore();
    const r1 = makeRecord();
    const r2 = makeRecord();
    await store.save(r1);
    await store.save(r2);
    await store.updateOutcome(r1.packId, { quality: 0.6 });

    const records = await store.getRecordsWithOutcomes();
    expect(records).toHaveLength(1);
    expect(records[0].packId).toBe(r1.packId);
  });

  it("handles non-existent file gracefully", async () => {
    const store = new FileFeedbackStore(
      path.join(tmpDir, "nonexistent.jsonl"),
      { disableLocking: true }
    );
    const records = await store.getRecords();
    expect(records).toHaveLength(0);
  });
});

describe("FileFeedbackStore cross-process merge", () => {
  const tmpDir = path.join(os.tmpdir(), "ce-adaptive-merge-test");

  afterEach(async () => {
    try {
      await fs.rm(tmpDir, { recursive: true });
    } catch {
      // Ignore cleanup errors
    }
  });

  function freshPath(): string {
    return path.join(
      tmpDir,
      `merge_${Math.random().toString(36).slice(2)}.jsonl`
    );
  }

  it("does not lose records when two stores write the same file", async () => {
    const storePath = freshPath();

    // Two independent instances simulate two processes sharing one file.
    const a = new FileFeedbackStore(storePath);
    const b = new FileFeedbackStore(storePath);

    const rec1 = makeRecord({ id: "rec1" });
    const rec2 = makeRecord({ id: "rec2" });
    const rec3 = makeRecord({ id: "rec3" });

    // Both load the same initial snapshot (rec1).
    await a.save(rec1);
    await b.getRecords(); // forces b to load rec1 into its in-memory list

    // A appends rec2, then B appends rec3. Before the fix, B's blind rewrite
    // would drop rec2.
    await a.save(rec2);
    await b.save(rec3);

    const onDisk = new FileFeedbackStore(storePath);
    const ids = new Set((await onDisk.getRecords()).map(r => r.id));

    expect(ids.has("rec1")).toBe(true);
    expect(ids.has("rec2")).toBe(true);
    expect(ids.has("rec3")).toBe(true);
    expect(ids.size).toBe(3);
  });

  it("attaches an outcome to a record created by another store instance", async () => {
    const storePath = freshPath();

    const creator = new FileFeedbackStore(storePath);
    const rec = makeRecord({ id: "shared", packId: "pack-shared" });
    await creator.save(rec);

    // A second instance that never loaded `rec` should still be able to attach
    // an outcome to it, because updateOutcome re-reads from disk under the lock.
    const reporter = new FileFeedbackStore(storePath);
    await reporter.updateOutcome("pack-shared", { quality: 0.77 });

    const verifier = new FileFeedbackStore(storePath);
    const [stored] = await verifier.getRecords();
    expect(stored.outcome?.quality).toBe(0.77);
  });

  it("clear() does not resurrect records from disk", async () => {
    const storePath = freshPath();

    const store = new FileFeedbackStore(storePath);
    await store.save(makeRecord({ id: "k1", segment: "keep" }));
    await store.save(makeRecord({ id: "r1", segment: "remove" }));

    await store.clear("remove");

    const verifier = new FileFeedbackStore(storePath);
    const records = await verifier.getRecords();
    expect(records).toHaveLength(1);
    expect(records[0].segment).toBe("keep");
  });
});
