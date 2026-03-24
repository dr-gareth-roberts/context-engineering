import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { InMemoryStore } from "./in-memory-store.js";
import { FileStore } from "./file-store.js";
import { SqliteStore } from "./sqlite-store.js";
import { createMemoryStore } from "./factory.js";
import { normalizeMemoryItem, decaySalience } from "./utils.js";
import { promises as fs } from "fs";
import os from "os";
import path from "path";

let tempDir: string;

beforeEach(async () => {
  tempDir = path.join(
    os.tmpdir(),
    `ce-memory-tests-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
  await fs.mkdir(tempDir, { recursive: true });
});

afterEach(async () => {
  await fs.rm(tempDir, { recursive: true, force: true });
});

function tempPath(name: string) {
  return path.join(tempDir, name);
}

describe("normalizeMemoryItem", () => {
  it("throws when content is missing", () => {
    expect(() => normalizeMemoryItem({})).toThrow("content");
  });

  it("throws when content is undefined", () => {
    expect(() => normalizeMemoryItem({ id: "a" })).toThrow("content");
  });

  it("accepts empty string content", () => {
    const item = normalizeMemoryItem({ content: "" });
    expect(item.content).toBe("");
  });
});

describe("decaySalience", () => {
  it("does not amplify salience for future createdAt timestamps", () => {
    const now = Date.now();
    const futureCreatedAt = new Date(now + 60_000).toISOString(); // 1 minute in the future
    const item = normalizeMemoryItem({
      content: "future item",
      salience: 0.8,
      createdAt: futureCreatedAt,
    });

    const decayed = decaySalience(item, now, 3600);
    // Future timestamps should produce zero age, so decayFactor = 1.0.
    // The decayed salience must equal the base salience exactly (no amplification).
    expect(decayed).toBe(0.8);
  });

  it("decays salience for past createdAt timestamps", () => {
    const now = Date.now();
    const halfLife = 3600; // 1 hour
    const pastCreatedAt = new Date(now - halfLife * 1000).toISOString(); // exactly 1 half-life ago
    const item = normalizeMemoryItem({
      content: "past item",
      salience: 1.0,
      createdAt: pastCreatedAt,
    });

    const decayed = decaySalience(item, now, halfLife);
    // After exactly one half-life, salience should be approximately 0.5
    expect(decayed).toBeCloseTo(0.5, 1);
  });

  it("returns base salience for items created exactly at now", () => {
    const now = Date.now();
    const item = normalizeMemoryItem({
      content: "current item",
      salience: 0.75,
      createdAt: new Date(now).toISOString(),
    });

    const decayed = decaySalience(item, now, 3600);
    expect(decayed).toBeCloseTo(0.75, 5);
  });
});

describe("InMemoryStore", () => {
  it("stores and retrieves items", async () => {
    const store = new InMemoryStore();
    const [item] = await store.put({ id: "a", content: "Hello" });
    const fetched = await store.get(item.id);
    expect(fetched?.content).toBe("Hello");
  });

  it("returns null for missing items", async () => {
    const store = new InMemoryStore();
    expect(await store.get("nonexistent")).toBeNull();
  });

  it("handles batch put", async () => {
    const store = new InMemoryStore();
    const items = await store.put([
      { id: "a", content: "First" },
      { id: "b", content: "Second" },
    ]);
    expect(items.length).toBe(2);
    expect(await store.get("a")).not.toBeNull();
    expect(await store.get("b")).not.toBeNull();
  });

  it("forgets items", async () => {
    const store = new InMemoryStore();
    await store.put({ id: "a", content: "Hello" });
    const deleted = await store.forget("a");
    expect(deleted).toBe(true);
    expect(await store.get("a")).toBeNull();
  });

  it("returns false when forgetting nonexistent items", async () => {
    const store = new InMemoryStore();
    expect(await store.forget("nope")).toBe(false);
  });

  it("queries with limit", async () => {
    const store = new InMemoryStore();
    await store.put([
      { id: "a", content: "First" },
      { id: "b", content: "Second" },
      { id: "c", content: "Third" },
    ]);
    const results = await store.query({ limit: 2 });
    expect(results.length).toBe(2);
  });

  it("queries with minSalience", async () => {
    const store = new InMemoryStore();
    await store.put([
      { id: "high", content: "Important", salience: 0.9 },
      { id: "low", content: "Meh", salience: 0.1 },
    ]);
    const results = await store.query({ minSalience: 0.5 });
    expect(results.length).toBe(1);
    expect(results[0].id).toBe("high");
  });

  it("queries with text filter", async () => {
    const store = new InMemoryStore();
    await store.put([
      { id: "a", content: "Hello world" },
      { id: "b", content: "Goodbye world" },
    ]);
    const results = await store.query({ text: "hello" });
    expect(results.length).toBe(1);
    expect(results[0].id).toBe("a");
  });

  it("filters expired items by default", async () => {
    const store = new InMemoryStore();
    const past = new Date(Date.now() - 10000).toISOString();
    await store.put({
      id: "old",
      content: "Expired",
      createdAt: past,
      ttlSeconds: 1,
    });
    const results = await store.query();
    expect(results.length).toBe(0);
  });

  it("includes expired items when requested", async () => {
    const store = new InMemoryStore();
    const past = new Date(Date.now() - 10000).toISOString();
    await store.put({
      id: "old",
      content: "Expired",
      createdAt: past,
      ttlSeconds: 1,
    });
    const results = await store.query({ includeExpired: true });
    expect(results.length).toBe(1);
  });

  it("upserts on duplicate id", async () => {
    const store = new InMemoryStore();
    await store.put({ id: "a", content: "Version 1" });
    await store.put({ id: "a", content: "Version 2" });
    const item = await store.get("a");
    expect(item?.content).toBe("Version 2");
  });

  it("generates id when missing", async () => {
    const store = new InMemoryStore();
    const [item] = await store.put({ content: "No ID" });
    expect(item.id).toBeDefined();
    expect(item.id.length).toBeGreaterThan(0);
  });

  it("expires items after TTL elapses", async () => {
    const store = new InMemoryStore();
    const pastDate = new Date(Date.now() - 5000).toISOString();
    await store.put({
      id: "ttl-item",
      content: "Short lived",
      createdAt: pastDate,
      ttlSeconds: 2,
    });

    // Item should be expired (created 5s ago, TTL is 2s)
    const expiredResults = await store.query();
    expect(expiredResults.find(i => i.id === "ttl-item")).toBeUndefined();

    // But with includeExpired it should still be there
    const allResults = await store.query({ includeExpired: true });
    expect(allResults.find(i => i.id === "ttl-item")).toBeDefined();

    // A non-expired item with TTL should still appear
    await store.put({
      id: "ttl-fresh",
      content: "Still alive",
      ttlSeconds: 9999,
    });
    const freshResults = await store.query();
    expect(freshResults.find(i => i.id === "ttl-fresh")).toBeDefined();
  });

  it("rejects put without content", async () => {
    const store = new InMemoryStore();
    await expect(store.put({ id: "a" })).rejects.toThrow("content");
  });

  it("throws on put/get/query/forget after close()", async () => {
    const store = new InMemoryStore();
    await store.put({ id: "a", content: "Hello" });
    await store.close();

    await expect(store.put({ id: "b", content: "new" })).rejects.toThrow(
      "InMemoryStore is closed"
    );
    await expect(store.get("a")).rejects.toThrow("InMemoryStore is closed");
    await expect(store.query()).rejects.toThrow("InMemoryStore is closed");
    await expect(store.forget("a")).rejects.toThrow("InMemoryStore is closed");
  });

  it("close() is idempotent", async () => {
    const store = new InMemoryStore();
    await store.close();
    await store.close(); // Should not throw
  });
});

describe("FileStore", () => {
  it("persists items to file", async () => {
    const filePath = tempPath("persist.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "f1", content: "Persisted" });
    const fetched = await store.get("f1");
    expect(fetched?.content).toBe("Persisted");
  });

  it("survives reload", async () => {
    const filePath = tempPath("reload.jsonl");
    const store1 = new FileStore(filePath);
    await store1.put({ id: "f1", content: "Data" });

    const store2 = new FileStore(filePath);
    const fetched = await store2.get("f1");
    expect(fetched?.content).toBe("Data");
  });

  it("handles empty file", async () => {
    const filePath = tempPath("empty.jsonl");
    await fs.writeFile(filePath, "");
    const store = new FileStore(filePath);
    const results = await store.query();
    expect(results).toEqual([]);
  });

  it("creates parent directories", async () => {
    const filePath = path.join(tempDir, "nested", "dir", "store.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "nested", content: "Deep" });
    const fetched = await store.get("nested");
    expect(fetched?.content).toBe("Deep");
  });

  it("forget removes an item and persists the change", async () => {
    const filePath = tempPath("forget.jsonl");
    const store1 = new FileStore(filePath);
    await store1.put([
      { id: "keep", content: "Keep me" },
      { id: "remove", content: "Remove me" },
    ]);

    const deleted = await store1.forget("remove");
    expect(deleted).toBe(true);
    expect(await store1.get("remove")).toBeNull();
    expect(await store1.get("keep")).not.toBeNull();

    // Verify persistence by loading a fresh store from the same file
    const store2 = new FileStore(filePath);
    expect(await store2.get("remove")).toBeNull();
    expect((await store2.get("keep"))?.content).toBe("Keep me");
  });

  it("throws on corrupted file by default", async () => {
    const filePath = tempPath("corrupted.jsonl");
    await fs.writeFile(
      filePath,
      '{"id":"good","content":"Valid item","createdAt":"2025-01-01T00:00:00Z"}\n' +
        "{broken json\n" +
        '{"id":"also-good","content":"Another valid item","createdAt":"2025-01-01T00:00:00Z"}\n'
    );
    const store = new FileStore(filePath);
    await expect(store.query()).rejects.toThrow();
  });

  it("skips corrupted lines when skipCorruptedLines is true", async () => {
    const filePath = tempPath("corrupted-skip.jsonl");
    await fs.writeFile(
      filePath,
      '{"id":"good","content":"Valid item","createdAt":"2025-01-01T00:00:00Z"}\n' +
        "{broken json\n" +
        '{"id":"also-good","content":"Another valid item","createdAt":"2025-01-01T00:00:00Z"}\n'
    );
    const store = new FileStore(filePath, { skipCorruptedLines: true });
    const results = await store.query({ includeExpired: true });
    expect(results.length).toBe(2);
    const ids = results.map(r => r.id);
    expect(ids).toContain("good");
    expect(ids).toContain("also-good");
  });

  it("handles file with only whitespace lines", async () => {
    const filePath = tempPath("whitespace.jsonl");
    await fs.writeFile(filePath, "\n  \n\n  \n");
    const store = new FileStore(filePath);
    const results = await store.query();
    expect(results).toEqual([]);
  });

  it("atomic write leaves no .tmp file after successful persist", async () => {
    const filePath = tempPath("atomic.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "a1", content: "Atomic test" });

    // The .tmp file should not exist after a successful write
    const tmpExists = await fs
      .access(filePath + ".tmp")
      .then(() => true)
      .catch(() => false);
    expect(tmpExists).toBe(false);

    // The actual file should exist with correct data
    const store2 = new FileStore(filePath);
    const item = await store2.get("a1");
    expect(item?.content).toBe("Atomic test");
  });

  it("handles concurrent puts without data loss", async () => {
    const filePath = tempPath("concurrent.jsonl");
    const store = new FileStore(filePath);

    // Rapidly put multiple items (sequential due to async nature)
    await Promise.all([
      store.put({ id: "c1", content: "First" }),
      store.put({ id: "c2", content: "Second" }),
      store.put({ id: "c3", content: "Third" }),
    ]);

    // All items should be present
    const results = await store.query();
    expect(results.length).toBe(3);
  });

  it("close() awaits pending writes", async () => {
    const filePath = tempPath("close.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "a", content: "Before close" });
    await store.close();

    // Data should be persisted after close
    const store2 = new FileStore(filePath);
    const item = await store2.get("a");
    expect(item?.content).toBe("Before close");
  });

  it("creates and removes lock file around writes", async () => {
    const filePath = tempPath("lock-lifecycle.jsonl");
    const lockPath = filePath + ".lock";
    const store = new FileStore(filePath);

    await store.put({ id: "lock1", content: "Locked write" });

    // After the write completes, the lock file should be cleaned up
    const lockExists = await fs
      .access(lockPath)
      .then(() => true)
      .catch(() => false);
    expect(lockExists).toBe(false);

    // Data should have been written correctly
    const fetched = await store.get("lock1");
    expect(fetched?.content).toBe("Locked write");
  });

  it("cleans up lock file on write error", async () => {
    const filePath = tempPath("lock-error.jsonl");
    const lockPath = filePath + ".lock";
    const store = new FileStore(filePath);

    // Seed the store so ensureLoaded resolves
    await store.put({ id: "seed", content: "Seed" });

    // Make the directory read-only so the .tmp write will fail
    const dir = path.dirname(filePath);
    // Create a store that points to a path inside a non-existent, unwritable location
    const badPath = path.join(dir, "readonly-dir", "store.jsonl");
    const badStore = new FileStore(badPath);

    // Trigger a load (creates the directory)
    await badStore.put({ id: "setup", content: "Setup" });

    // Now make the parent read-only to force a write failure
    const badDir = path.dirname(badPath);
    await fs.chmod(badDir, 0o444);

    try {
      await expect(
        badStore.put({ id: "fail", content: "Should fail" })
      ).rejects.toThrow();

      // Lock file should be cleaned up even after error
      const badLockPath = badPath + ".lock";
      const lockExists = await fs
        .access(badLockPath)
        .then(() => true)
        .catch(() => false);
      expect(lockExists).toBe(false);
    } finally {
      // Restore permissions for cleanup
      await fs.chmod(badDir, 0o755);
    }
  });

  it("disableLocking skips lock entirely", async () => {
    const filePath = tempPath("no-lock.jsonl");
    const lockPath = filePath + ".lock";
    const store = new FileStore(filePath, { disableLocking: true });

    // We need to spy to confirm the lock file is never created.
    // Instead, we verify the write succeeds and no lock file remains.
    await store.put({ id: "nolock1", content: "No lock" });

    const lockExists = await fs
      .access(lockPath)
      .then(() => true)
      .catch(() => false);
    expect(lockExists).toBe(false);

    // Verify data was written correctly
    const store2 = new FileStore(filePath, { disableLocking: true });
    const fetched = await store2.get("nolock1");
    expect(fetched?.content).toBe("No lock");
  });

  it("detects and removes stale lock files", async () => {
    const filePath = tempPath("stale-lock.jsonl");
    const lockPath = filePath + ".lock";

    // Ensure parent directory exists
    await fs.mkdir(path.dirname(filePath), { recursive: true });

    // Create a "stale" lock file manually
    await fs.writeFile(
      lockPath,
      JSON.stringify({ pid: 99999, timestamp: "2020-01-01T00:00:00Z" })
    );

    // Backdate the lock file mtime so it appears stale
    const pastTime = new Date(Date.now() - 20000); // 20 seconds ago
    await fs.utimes(lockPath, pastTime, pastTime);

    // staleLockAge=5000 means anything older than 5s is stale
    const store = new FileStore(filePath, { staleLockAge: 5000 });
    await store.put({ id: "after-stale", content: "Recovered" });

    // Lock file should be cleaned up
    const lockExists = await fs
      .access(lockPath)
      .then(() => true)
      .catch(() => false);
    expect(lockExists).toBe(false);

    // Data should be written correctly
    const fetched = await store.get("after-stale");
    expect(fetched?.content).toBe("Recovered");
  });

  it("throws on put/get/query/forget after close()", async () => {
    const filePath = tempPath("close-guard.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "a", content: "data" });
    await store.close();

    await expect(store.put({ id: "b", content: "new" })).rejects.toThrow(
      "FileStore is closed"
    );
    await expect(store.get("a")).rejects.toThrow("FileStore is closed");
    await expect(store.query()).rejects.toThrow("FileStore is closed");
    await expect(store.forget("a")).rejects.toThrow("FileStore is closed");
  });

  it("close() is idempotent", async () => {
    const filePath = tempPath("close-idem.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "a", content: "data" });
    await store.close();
    await store.close(); // Should not throw
  });
});

describe("SqliteStore", () => {
  it("applies limit after JS-side decay filtering", async () => {
    const store = new SqliteStore(tempPath("limit.db"));
    const now = Date.now();

    await store.put([
      {
        id: "old-high",
        content: "alpha old",
        salience: 10,
        createdAt: new Date(now - 10 * 24 * 60 * 60 * 1000).toISOString(),
      },
      {
        id: "fresh-medium",
        content: "alpha fresh",
        salience: 8,
        createdAt: new Date(now - 60 * 1000).toISOString(),
      },
      {
        id: "fresh-low",
        content: "alpha fresh second",
        salience: 7,
        createdAt: new Date(now - 60 * 1000).toISOString(),
      },
    ]);

    const results = await store.query({
      text: "alpha",
      halfLifeSeconds: 60 * 60,
      limit: 2,
      now,
    });

    expect(results.map(item => item.id)).toEqual(["fresh-medium", "fresh-low"]);
    await store.close();
  });

  it("stores and retrieves items", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "s1", content: "SQLite data" });
    const fetched = await store.get("s1");
    expect(fetched?.content).toBe("SQLite data");
    await store.close();
  });

  it("handles TTL expiration", async () => {
    const store = new SqliteStore(":memory:");
    const past = new Date(Date.now() - 5000).toISOString();
    await store.put({
      id: "ttl-1",
      content: "Old memory",
      createdAt: past,
      ttlSeconds: 1,
    });
    const results = await store.query({ now: Date.now() });
    expect(results.length).toBe(0);
    await store.close();
  });

  it("upserts on duplicate id", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "s1", content: "Version 1" });
    await store.put({ id: "s1", content: "Version 2" });
    const fetched = await store.get("s1");
    expect(fetched?.content).toBe("Version 2");
    await store.close();
  });

  it("batch inserts in transaction", async () => {
    const store = new SqliteStore(":memory:");
    const items = await store.put([
      { id: "b1", content: "First" },
      { id: "b2", content: "Second" },
    ]);
    expect(items.length).toBe(2);
    await store.close();
  });

  it("rejects invalid table names", () => {
    expect(
      () => new SqliteStore(":memory:", { tableName: "DROP TABLE; --" })
    ).toThrow();
  });

  it("accepts valid table names", async () => {
    const store = new SqliteStore(":memory:", { tableName: "my_items" });
    expect(store).toBeDefined();
    await store.close();
  });

  it("preserves metadata", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({
      id: "meta",
      content: "With metadata",
      metadata: { key: "value", nested: { a: 1 } },
    });
    const fetched = await store.get("meta");
    expect(fetched?.metadata).toEqual({ key: "value", nested: { a: 1 } });
    await store.close();
  });

  it("forgets items", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "del", content: "Delete me" });
    const deleted = await store.forget("del");
    expect(deleted).toBe(true);
    expect(await store.get("del")).toBeNull();
    await store.close();
  });

  it("queries with minSalience filter", async () => {
    const store = new SqliteStore(":memory:");
    await store.put([
      { id: "high", content: "Important", salience: 0.9 },
      { id: "medium", content: "Moderate", salience: 0.5 },
      { id: "low", content: "Meh", salience: 0.1 },
    ]);
    const results = await store.query({ minSalience: 0.5 });
    expect(results.length).toBe(2);
    const ids = results.map(r => r.id);
    expect(ids).toContain("high");
    expect(ids).toContain("medium");
    expect(ids).not.toContain("low");
    await store.close();
  });

  it("queries with text filter", async () => {
    const store = new SqliteStore(":memory:");
    await store.put([
      { id: "a", content: "Hello world" },
      { id: "b", content: "Goodbye world" },
      { id: "c", content: "Hello universe" },
    ]);
    const results = await store.query({ text: "hello" });
    expect(results.length).toBe(2);
    const ids = results.map(r => r.id);
    expect(ids).toContain("a");
    expect(ids).toContain("c");
    expect(ids).not.toContain("b");
    await store.close();
  });

  it("handles LIKE wildcard characters in text query", async () => {
    const store = new SqliteStore(":memory:");
    await store.put([
      { id: "a", content: "100% complete" },
      { id: "b", content: "100 complete" },
      { id: "c", content: "a_b value" },
      { id: "d", content: "axb value" },
    ]);
    // The % character should be treated as a literal, not a wildcard
    const percentResults = await store.query({ text: "100%" });
    expect(percentResults.length).toBe(1);
    expect(percentResults[0].id).toBe("a");

    // The _ character should be treated as a literal, not a wildcard
    const underscoreResults = await store.query({ text: "a_b" });
    expect(underscoreResults.length).toBe(1);
    expect(underscoreResults[0].id).toBe("c");
    await store.close();
  });

  it("throws on put/get/query/forget after close()", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "a", content: "data" });
    await store.close();

    await expect(store.put({ id: "b", content: "new" })).rejects.toThrow(
      "SqliteStore is closed"
    );
    await expect(store.get("a")).rejects.toThrow("SqliteStore is closed");
    await expect(store.query()).rejects.toThrow("SqliteStore is closed");
    await expect(store.forget("a")).rejects.toThrow("SqliteStore is closed");
  });

  it("close() is idempotent", async () => {
    const store = new SqliteStore(":memory:");
    await store.close();
    await store.close(); // Should not throw
  });
});

describe("createMemoryStore", () => {
  it("creates in-memory store", () => {
    const store = createMemoryStore("memory");
    expect(store).toBeInstanceOf(InMemoryStore);
  });

  it("creates file store", () => {
    const store = createMemoryStore("file", {
      path: tempPath("factory.jsonl"),
    });
    expect(store).toBeInstanceOf(FileStore);
  });

  it("creates file store with skipCorruptedLines", () => {
    const store = createMemoryStore("file", {
      path: tempPath("factory-skip.jsonl"),
      skipCorruptedLines: true,
    });
    expect(store).toBeInstanceOf(FileStore);
  });

  it("creates sqlite store", () => {
    const store = createMemoryStore("sqlite", { path: ":memory:" });
    expect(store).toBeInstanceOf(SqliteStore);
  });

  it("throws for unknown type", () => {
    expect(() => createMemoryStore("postgres" as any)).toThrow(
      "Unknown memory store type"
    );
  });

  it("throws when file store missing path", () => {
    expect(() => createMemoryStore("file")).toThrow("path");
  });

  it("throws when sqlite store missing path", () => {
    expect(() => createMemoryStore("sqlite")).toThrow("path");
  });

  it("throws when redis store missing url and redisOptions", () => {
    expect(() => createMemoryStore("redis")).toThrow("url");
  });
});
