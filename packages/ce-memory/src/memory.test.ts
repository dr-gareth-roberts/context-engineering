import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { InMemoryStore } from "./in-memory-store";
import { FileStore } from "./file-store";
import { SqliteStore } from "./sqlite-store";
import { createMemoryStore } from "./factory";
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
});

describe("SqliteStore", () => {
  it("stores and retrieves items", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "s1", content: "SQLite data" });
    const fetched = await store.get("s1");
    expect(fetched?.content).toBe("SQLite data");
    store.close();
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
    store.close();
  });

  it("upserts on duplicate id", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "s1", content: "Version 1" });
    await store.put({ id: "s1", content: "Version 2" });
    const fetched = await store.get("s1");
    expect(fetched?.content).toBe("Version 2");
    store.close();
  });

  it("batch inserts in transaction", async () => {
    const store = new SqliteStore(":memory:");
    const items = await store.put([
      { id: "b1", content: "First" },
      { id: "b2", content: "Second" },
    ]);
    expect(items.length).toBe(2);
    store.close();
  });

  it("rejects invalid table names", () => {
    expect(
      () => new SqliteStore(":memory:", { tableName: "DROP TABLE; --" })
    ).toThrow();
  });

  it("accepts valid table names", () => {
    const store = new SqliteStore(":memory:", { tableName: "my_items" });
    expect(store).toBeDefined();
    store.close();
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
    store.close();
  });

  it("forgets items", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "del", content: "Delete me" });
    const deleted = await store.forget("del");
    expect(deleted).toBe(true);
    expect(await store.get("del")).toBeNull();
    store.close();
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

  it("creates sqlite store", () => {
    const store = createMemoryStore("sqlite", { path: ":memory:" });
    expect(store).toBeInstanceOf(SqliteStore);
  });

  it("throws for unknown type", () => {
    expect(() => createMemoryStore("redis" as any)).toThrow();
  });

  it("throws when file store missing path", () => {
    expect(() => createMemoryStore("file")).toThrow("path");
  });

  it("throws when sqlite store missing path", () => {
    expect(() => createMemoryStore("sqlite")).toThrow("path");
  });
});
