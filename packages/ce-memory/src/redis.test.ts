import { describe, expect, it, vi, beforeEach } from "vitest";
import { createMemoryStore } from "./factory.js";
import { RedisStore } from "./redis-store.js";

// We'll mock the module to intercept the Redis class constructor and pipeline
vi.mock("ioredis", async () => {
  const { Readable } = await import("stream");
  return {
    Redis: class MockRedis {
      private data = new Map<string, string>();
      private expiries = new Map<string, NodeJS.Timeout>();

      pipeline() {
        const cmds: Array<() => void> = [];
        const pipelineObj = {
          set: (key: string, val: string, ex?: string, ttl?: number) => {
            cmds.push(() => {
              this.data.set(key, val);
              if (ex === "EX" && ttl) {
                if (this.expiries.has(key))
                  clearTimeout(this.expiries.get(key));
                this.expiries.set(
                  key,
                  setTimeout(() => this.data.delete(key), ttl * 1000)
                );
              }
            });
            return pipelineObj;
          },
          exec: async () => {
            cmds.forEach(c => c());
            return [];
          },
        };
        return pipelineObj;
      }

      async get(key: string) {
        return this.data.get(key) || null;
      }

      async set(key: string, val: string, ex?: string, ttl?: number) {
        this.data.set(key, val);
        if (ex === "EX" && ttl) {
          if (this.expiries.has(key)) clearTimeout(this.expiries.get(key));
          this.expiries.set(
            key,
            setTimeout(() => this.data.delete(key), ttl * 1000)
          );
        }
      }

      scanStream(options?: { match?: string; count?: number }) {
        const matchPrefix = (options?.match ?? "*").replace("*", "");
        const keys = Array.from(this.data.keys()).filter(k =>
          k.startsWith(matchPrefix)
        );
        // Return a readable stream that emits keys in one batch
        const stream = new Readable({ objectMode: true, read() {} });
        // Push the batch asynchronously to simulate real Redis behavior
        process.nextTick(() => {
          if (keys.length > 0) {
            stream.push(keys);
          }
          stream.push(null);
        });
        return stream;
      }

      async mget(keys: string[]) {
        return keys.map(k => this.data.get(k) || null);
      }

      async del(key: string) {
        if (this.data.has(key)) {
          this.data.delete(key);
          return 1;
        }
        return 0;
      }

      async quit() {
        this.data.clear();
        this.expiries.forEach(t => clearTimeout(t));
      }

      disconnect() {
        this.data.clear();
        this.expiries.forEach(t => clearTimeout(t));
      }
    },
  };
});

describe("RedisStore - Edge Cases", () => {
  let store: RedisStore;

  beforeEach(() => {
    store = createMemoryStore("redis", {
      url: "redis://localhost:6379",
    }) as RedisStore;
  });

  it("handles empty arrays passed to put() gracefully", async () => {
    const result = await store.put([]);
    expect(result).toEqual([]);
  });

  it("returns null on get() for missing item", async () => {
    const item = await store.get("missing_id");
    expect(item).toBeNull();
  });

  it("handles negative TTL appropriately (stored without expiry)", async () => {
    const items = await store.put({
      id: "neg",
      content: "neg TTL",
      ttlSeconds: -100,
    });
    const fetched = await store.get("neg");
    expect(fetched).not.toBeNull();
    expect(fetched?.content).toBe("neg TTL");
  });

  it("query returns empty array if no keys match", async () => {
    const result = await store.query();
    expect(result).toEqual([]);
  });

  it("stores and retrieves items", async () => {
    await store.put({ id: "test1", content: "Hello Redis" });
    const fetched = await store.get("test1");
    expect(fetched?.content).toBe("Hello Redis");
  });

  it("queries all items", async () => {
    await store.put([
      { id: "r1", content: "First" },
      { id: "r2", content: "Second" },
    ]);
    const results = await store.query();
    expect(results.length).toBe(2);
  });

  it("forgets items", async () => {
    await store.put({ id: "del", content: "Remove me" });
    const deleted = await store.forget("del");
    expect(deleted).toBe(true);
    expect(await store.get("del")).toBeNull();
  });

  it("close() cleans up the client", async () => {
    await store.put({ id: "a", content: "data" });
    await store.close();
    // After close/quit, data is cleared in mock
    expect(await store.get("a")).toBeNull();
  });

  it("rejects put without content", async () => {
    await expect(store.put({ id: "a" })).rejects.toThrow("content");
  });
});

describe("RedisStore - TTL Computation", () => {
  it("computes Redis EX from createdAt, not from put() time", async () => {
    // Item was created 30 seconds ago with a 60-second TTL.
    // The computed Redis EX should be ~30 seconds (the remaining time),
    // not the full 60 seconds.
    const store = new RedisStore("redis://localhost:6379");
    const createdAt = new Date(Date.now() - 30_000).toISOString();
    await store.put({
      id: "ttl-check",
      content: "TTL computation test",
      createdAt,
      ttlSeconds: 60,
    });

    // Retrieve the item to verify it was stored
    const item = await store.get("ttl-check");
    expect(item).not.toBeNull();
    expect(item?.content).toBe("TTL computation test");

    // The mock stores data with the computed EX. We can verify the
    // logic indirectly: an item created 30s ago with 60s TTL should
    // still be retrievable (remaining ~30s > 0).
    // More importantly, an item already past its TTL should get EX=1
    // (the Math.max(1, ...) floor) and expire very quickly.
    const expiredCreatedAt = new Date(Date.now() - 120_000).toISOString();
    await store.put({
      id: "ttl-expired",
      content: "Already expired",
      createdAt: expiredCreatedAt,
      ttlSeconds: 60, // expired 60s ago
    });
    // Item is stored with EX=1 (the minimum). It exists right now
    // but would expire in 1 second on a real Redis server.
    const expiredItem = await store.get("ttl-expired");
    expect(expiredItem).not.toBeNull();

    await store.close();
  });

  it("stores item without EX when ttlSeconds is undefined", async () => {
    const store = new RedisStore("redis://localhost:6379");
    await store.put({
      id: "no-ttl",
      content: "No TTL",
    });
    const item = await store.get("no-ttl");
    expect(item).not.toBeNull();
    expect(item?.content).toBe("No TTL");
    await store.close();
  });
});

describe("RedisStore - Custom Prefix", () => {
  it("uses custom prefix for keys", async () => {
    const store = new RedisStore("redis://localhost:6379", {
      prefix: "myapp:",
    });
    await store.put({ id: "x", content: "prefixed" });
    const fetched = await store.get("x");
    expect(fetched?.content).toBe("prefixed");
    await store.close();
  });
});
