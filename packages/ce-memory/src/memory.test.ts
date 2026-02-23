import { describe, expect, it } from "vitest";
import { InMemoryStore } from "./in-memory-store";
import { FileStore } from "./file-store";
import { SqliteStore } from "./sqlite-store";
import { promises as fs } from "fs";
import os from "os";
import path from "path";

const tempDir = path.join(os.tmpdir(), "ce-memory-tests");

function tempPath(name: string) {
  return path.join(tempDir, name);
}

describe("memory stores", () => {
  it("stores and retrieves items in memory", async () => {
    const store = new InMemoryStore();
    const [item] = await store.put({ id: "a", content: "Hello" });
    const fetched = await store.get(item.id);
    expect(fetched?.content).toBe("Hello");
  });

  it("persists items to file", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = tempPath("memory.jsonl");
    await fs.writeFile(filePath, "");

    const store = new FileStore(filePath);
    await store.put({ id: "file-1", content: "Persisted" });
    const fetched = await store.get("file-1");
    expect(fetched?.content).toBe("Persisted");
  });

  it("handles TTL expiration in sqlite", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const dbPath = tempPath("memory.sqlite");
    const store = new SqliteStore(dbPath);

    const past = new Date(Date.now() - 5000).toISOString();
    await store.put({
      id: "ttl-1",
      content: "Old memory",
      createdAt: past,
      ttlSeconds: 1
    });

    const results = await store.query({ now: Date.now() });
    expect(results.length).toBe(0);
  });
});
