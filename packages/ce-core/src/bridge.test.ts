import { describe, expect, it } from "vitest";
import { toContextItem, memoryToContext } from "./bridge.js";
import { defaultItemScorer } from "./score.js";
import type { MemoryItem } from "./types.js";

const NOW = new Date("2025-01-15T12:00:00Z").getTime();

function makeMemory(overrides: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id: "mem-1",
    content: "Remember to check the API rate limits",
    createdAt: new Date(NOW - 60 * 1000).toISOString(), // 1 minute ago
    salience: 0.8,
    ...overrides,
  };
}

describe("toContextItem", () => {
  it("maps basic fields from MemoryItem to ContextItem", () => {
    const memory = makeMemory();
    const item = toContextItem(memory, { now: NOW });

    expect(item.id).toBe("mem-1");
    expect(item.content).toBe("Remember to check the API rate limits");
    expect(item.kind).toBe("memory");
    expect(item.priority).toBe(5);
  });

  it("maps salience to metadata.salience", () => {
    const memory = makeMemory({ salience: 0.9 });
    const item = toContextItem(memory, { now: NOW });

    expect(item.metadata?.salience).toBe(0.9);
  });

  it("defaults salience to 1.0 when not provided", () => {
    const memory = makeMemory({ salience: undefined });
    const item = toContextItem(memory, { now: NOW });

    expect(item.metadata?.salience).toBe(1.0);
  });

  it("preserves createdAt in metadata", () => {
    const memory = makeMemory();
    const item = toContextItem(memory, { now: NOW });

    expect(item.metadata?.createdAt).toBe(memory.createdAt);
  });

  it("includes updatedAt in metadata when present", () => {
    const updatedAt = new Date(NOW - 30 * 1000).toISOString();
    const memory = makeMemory({ updatedAt });
    const item = toContextItem(memory, { now: NOW });

    expect(item.metadata?.updatedAt).toBe(updatedAt);
  });

  it("omits updatedAt from metadata when not present", () => {
    const memory = makeMemory({ updatedAt: undefined });
    const item = toContextItem(memory, { now: NOW });

    expect(item.metadata).not.toHaveProperty("updatedAt");
  });

  it("merges existing metadata from the memory item", () => {
    const memory = makeMemory({ metadata: { source: "slack", channel: "#eng" } });
    const item = toContextItem(memory, { now: NOW });

    expect(item.metadata?.source).toBe("slack");
    expect(item.metadata?.channel).toBe("#eng");
    expect(item.metadata?.salience).toBe(0.8);
  });
});

describe("recency calculation", () => {
  it("gives high recency to very recent items", () => {
    const memory = makeMemory({
      createdAt: new Date(NOW - 1000).toISOString(), // 1 second ago
    });
    const item = toContextItem(memory, { now: NOW });

    // 1 second ago with 3600s half-life should be very close to 10
    expect(item.recency).toBeGreaterThan(9.9);
  });

  it("gives recency of ~5 at exactly one half-life", () => {
    const memory = makeMemory({
      createdAt: new Date(NOW - 3600 * 1000).toISOString(), // 1 hour ago
    });
    const item = toContextItem(memory, { now: NOW });

    // At exactly one half-life, recency should be 5.0
    expect(item.recency).toBeCloseTo(5.0, 1);
  });

  it("gives low recency to old items", () => {
    const memory = makeMemory({
      createdAt: new Date(NOW - 24 * 3600 * 1000).toISOString(), // 24 hours ago
    });
    const item = toContextItem(memory, { now: NOW });

    // 24 hours with 1-hour half-life: 0.5^24 * 10 ~ 0.0000006
    expect(item.recency).toBeLessThan(0.01);
  });

  it("gives recency of 10 for items created at exactly now", () => {
    const memory = makeMemory({
      createdAt: new Date(NOW).toISOString(),
    });
    const item = toContextItem(memory, { now: NOW });

    expect(item.recency).toBe(10);
  });
});

describe("custom BridgeOptions", () => {
  it("applies custom priority", () => {
    const memory = makeMemory();
    const item = toContextItem(memory, { now: NOW, priority: 8 });

    expect(item.priority).toBe(8);
  });

  it("applies custom kind", () => {
    const memory = makeMemory();
    const item = toContextItem(memory, { now: NOW, kind: "episodic" });

    expect(item.kind).toBe("episodic");
  });

  it("applies custom recencyHalfLife", () => {
    const memory = makeMemory({
      createdAt: new Date(NOW - 60 * 1000).toISOString(), // 1 minute ago
    });

    // With 60-second half-life, 1 minute ago should give recency ~5
    const item = toContextItem(memory, { now: NOW, recencyHalfLife: 60 });
    expect(item.recency).toBeCloseTo(5.0, 1);
  });

  it("uses Date.now() when now is not specified", () => {
    const memory = makeMemory({
      createdAt: new Date().toISOString(),
    });
    const item = toContextItem(memory);

    // Should be very close to 10 since createdAt is ~now
    expect(item.recency).toBeGreaterThan(9.0);
  });
});

describe("memoryToContext", () => {
  it("converts an array of MemoryItems", () => {
    const memories: MemoryItem[] = [
      makeMemory({ id: "a" }),
      makeMemory({ id: "b" }),
      makeMemory({ id: "c" }),
    ];
    const items = memoryToContext(memories, { now: NOW });

    expect(items).toHaveLength(3);
    expect(items[0].id).toBe("a");
    expect(items[1].id).toBe("b");
    expect(items[2].id).toBe("c");
  });

  it("applies the same options to all items", () => {
    const memories: MemoryItem[] = [
      makeMemory({ id: "a" }),
      makeMemory({ id: "b" }),
    ];
    const items = memoryToContext(memories, {
      now: NOW,
      priority: 7,
      kind: "semantic",
    });

    for (const item of items) {
      expect(item.priority).toBe(7);
      expect(item.kind).toBe("semantic");
    }
  });

  it("handles empty array", () => {
    const items = memoryToContext([]);
    expect(items).toEqual([]);
  });
});

describe("integration with defaultItemScorer", () => {
  it("produces items that score greater than zero", () => {
    const memory = makeMemory({ salience: 0.8 });
    const item = toContextItem(memory, { now: NOW });
    const score = defaultItemScorer(item);

    // priority(5) * 1.0 + recency(~9.99) * 0.7 + salience(0.8) * 0.5
    // = 5 + ~7.0 + 0.4 = ~12.4
    expect(score).toBeGreaterThan(0);
  });

  it("scores recent items higher than old items", () => {
    const recent = makeMemory({
      id: "recent",
      createdAt: new Date(NOW - 60 * 1000).toISOString(), // 1 minute ago
    });
    const old = makeMemory({
      id: "old",
      createdAt: new Date(NOW - 24 * 3600 * 1000).toISOString(), // 24 hours ago
    });

    const recentItem = toContextItem(recent, { now: NOW });
    const oldItem = toContextItem(old, { now: NOW });

    expect(defaultItemScorer(recentItem)).toBeGreaterThan(
      defaultItemScorer(oldItem),
    );
  });

  it("scores high-salience items higher than low-salience items", () => {
    const highSalience = makeMemory({
      id: "high",
      salience: 1.0,
      createdAt: new Date(NOW - 60 * 1000).toISOString(),
    });
    const lowSalience = makeMemory({
      id: "low",
      salience: 0.1,
      createdAt: new Date(NOW - 60 * 1000).toISOString(),
    });

    const highItem = toContextItem(highSalience, { now: NOW });
    const lowItem = toContextItem(lowSalience, { now: NOW });

    expect(defaultItemScorer(highItem)).toBeGreaterThan(
      defaultItemScorer(lowItem),
    );
  });
});
