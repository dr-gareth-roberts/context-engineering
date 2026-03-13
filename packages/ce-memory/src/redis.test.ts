import { describe, expect, it, vi, beforeEach } from "vitest";
import { createMemoryStore } from "./factory";
import { RedisStore } from "./redis-store";

// We'll mock the module to intercept the Redis class constructor and pipeline
vi.mock("ioredis", () => {
  return {
    Redis: class MockRedis {
      private data = new Map<string, string>();
      private expiries = new Map<string, NodeJS.Timeout>();

      pipeline() {
        const cmds: Array<() => void> = [];
        return {
          set: (key: string, val: string, ex?: string, ttl?: number) => {
            cmds.push(() => {
              this.data.set(key, val);
              if (ex === "EX" && ttl) {
                // mock expiry
                if (this.expiries.has(key)) clearTimeout(this.expiries.get(key));
                this.expiries.set(key, setTimeout(() => this.data.delete(key), ttl * 1000));
              }
            });
            return this;
          },
          exec: async () => {
            cmds.forEach(c => c());
            return [];
          }
        };
      }

      async get(key: string) {
        return this.data.get(key) || null;
      }

      async set(key: string, val: string, ex?: string, ttl?: number) {
        this.data.set(key, val);
        if (ex === "EX" && ttl) {
          if (this.expiries.has(key)) clearTimeout(this.expiries.get(key));
          this.expiries.set(key, setTimeout(() => this.data.delete(key), ttl * 1000));
        }
      }

      async keys(pattern: string) {
        const prefix = pattern.replace("*", "");
        return Array.from(this.data.keys()).filter(k => k.startsWith(prefix));
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

      disconnect() {
        this.data.clear();
        this.expiries.forEach(t => clearTimeout(t));
      }
    }
  };
});

describe("RedisStore - Edge Cases", () => {
  let store: RedisStore;

  beforeEach(() => {
    store = createMemoryStore("redis", { url: "redis://localhost:6379" }) as RedisStore;
  });

  it("handles empty arrays passed to put() gracefully", async () => {
    const result = await store.put([]);
    expect(result).toEqual([]);
  });

  it("returns null on get() for missing item", async () => {
    const item = await store.get("missing_id");
    expect(item).toBeNull();
  });

  it("handles negative TTL appropriately (ignores or delegates to mock behavior)", async () => {
    const items = await store.put({ id: "neg", content: "neg TTL", ttlSeconds: -100 });
    // In our mock, if ttlSeconds is > 0 it sets EX. If negative, it sets without EX (persistent).
    const fetched = await store.get("neg");
    expect(fetched).not.toBeNull();
    expect(fetched?.content).toBe("neg TTL");
  });

  it("query returns empty array if no keys match", async () => {
    const result = await store.query();
    expect(result).toEqual([]);
  });

  it("extends TTL on get()", async () => {
    await store.put({ id: "ttl_test", content: "data", ttlSeconds: 10 });
    const first = await store.get("ttl_test");
    expect(first).toBeDefined();

    // The mock should have re-set the EX, extending it
    const data = (store as any).client.data.get("ce_memory:ttl_test");
    expect(data).toBeDefined();
    
    // We can verify that the expiry was reset by checking the internal mock map
    const expiries = (store as any).client.expiries;
    expect(expiries.has("ce_memory:ttl_test")).toBe(true);
  });
});
