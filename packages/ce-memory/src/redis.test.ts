import { describe, expect, it, vi, beforeEach } from "vitest";
import { createMemoryStore } from "./factory.js";
import { RedisStore } from "./redis-store.js";

// Track pipeline set calls for assertions
let lastPipelineSetCalls: Array<{ key: string; val: string; args: unknown[] }> =
  [];
// Allow tests to inject pipeline errors
let pipelineExecOverride: (() => Promise<unknown>) | null = null;

// We'll mock the module to intercept the Redis class constructor and pipeline
vi.mock("ioredis", async () => {
  const { Readable } = await import("stream");
  return {
    Redis: class MockRedis {
      private data = new Map<string, string>();

      pipeline() {
        const cmds: Array<() => [null, string]> = [];
        lastPipelineSetCalls = [];
        const pipelineObj = {
          set: (key: string, val: string, ...args: unknown[]) => {
            lastPipelineSetCalls.push({ key, val, args });
            cmds.push(() => {
              this.data.set(key, val);
              return [null, "OK"];
            });
            return pipelineObj;
          },
          exec: async () => {
            if (pipelineExecOverride) {
              return pipelineExecOverride();
            }
            return cmds.map(c => c());
          },
        };
        return pipelineObj;
      }

      async get(key: string) {
        return this.data.get(key) || null;
      }

      async set(key: string, val: string) {
        this.data.set(key, val);
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
      }

      disconnect() {
        this.data.clear();
      }
    },
  };
});

describe("RedisStore - Edge Cases", () => {
  let store: RedisStore;

  beforeEach(() => {
    lastPipelineSetCalls = [];
    pipelineExecOverride = null;
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
    // After close, operations should throw
    await expect(store.get("a")).rejects.toThrow("RedisStore is closed");
  });

  it("rejects put without content", async () => {
    await expect(store.put({ id: "a" })).rejects.toThrow("content");
  });
});

describe("RedisStore - TTL via applyQueryFilter", () => {
  it("put() stores items without Redis EX", async () => {
    const store = new RedisStore("redis://localhost:6379");
    lastPipelineSetCalls = [];
    await store.put({
      id: "ttl-check",
      content: "TTL stored in payload",
      ttlSeconds: 60,
    });

    // The pipeline.set call should NOT include "EX" arguments
    expect(lastPipelineSetCalls.length).toBe(1);
    expect(lastPipelineSetCalls[0].args).toEqual([]);

    // The ttlSeconds should be in the JSON payload
    const payload = JSON.parse(lastPipelineSetCalls[0].val);
    expect(payload.ttlSeconds).toBe(60);

    await store.close();
  });

  it("expired items are excluded from query() by default", async () => {
    const store = new RedisStore("redis://localhost:6379");
    const past = new Date(Date.now() - 10_000).toISOString();
    await store.put({
      id: "old",
      content: "Expired item",
      createdAt: past,
      ttlSeconds: 1,
    });

    const results = await store.query();
    expect(results.length).toBe(0);

    await store.close();
  });

  it("expired items are included with query({ includeExpired: true })", async () => {
    const store = new RedisStore("redis://localhost:6379");
    const past = new Date(Date.now() - 10_000).toISOString();
    await store.put({
      id: "old",
      content: "Expired item",
      createdAt: past,
      ttlSeconds: 1,
    });

    const results = await store.query({ includeExpired: true });
    expect(results.length).toBe(1);
    expect(results[0].id).toBe("old");

    await store.close();
  });

  it("pipeline errors cause put() to throw", async () => {
    const store = new RedisStore("redis://localhost:6379");
    pipelineExecOverride = async () => {
      return [[new Error("READONLY You can't write against a read only replica"), null]];
    };

    await expect(
      store.put({ id: "fail", content: "Should fail" })
    ).rejects.toThrow("Redis pipeline command failed");

    pipelineExecOverride = null;
    await store.close();
  });

  it("throws on operations after close()", async () => {
    const store = new RedisStore("redis://localhost:6379");
    await store.put({ id: "a", content: "data" });
    await store.close();

    await expect(store.put({ id: "b", content: "new" })).rejects.toThrow(
      "RedisStore is closed"
    );
    await expect(store.get("a")).rejects.toThrow("RedisStore is closed");
    await expect(store.query()).rejects.toThrow("RedisStore is closed");
    await expect(store.forget("a")).rejects.toThrow("RedisStore is closed");
  });

  it("close() is idempotent", async () => {
    const store = new RedisStore("redis://localhost:6379");
    await store.close();
    await store.close(); // Should not throw
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
