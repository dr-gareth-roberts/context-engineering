import { describe, expect, it } from "vitest";
import {
  classifyVolatility,
  packWithCacheTopology,
  packWithCacheTopologyAsync,
} from "./cache-topology.js";
import type { ContextItem } from "./types.js";
import { createContextItem } from "./types.js";

function makeItem(
  id: string,
  kind: string,
  priority: number,
  tokens: number
): ContextItem {
  return { id, content: `content-${id}`, kind, priority, tokens };
}

describe("classifyVolatility", () => {
  it("classifies system/tool/schema as static", () => {
    expect(classifyVolatility({ id: "a", content: "", kind: "system" })).toBe(
      "static"
    );
    expect(classifyVolatility({ id: "a", content: "", kind: "tool" })).toBe(
      "static"
    );
    expect(classifyVolatility({ id: "a", content: "", kind: "schema" })).toBe(
      "static"
    );
    expect(classifyVolatility({ id: "a", content: "", kind: "example" })).toBe(
      "static"
    );
    expect(
      classifyVolatility({ id: "a", content: "", kind: "instruction" })
    ).toBe("static");
  });

  it("classifies memory/conversation/history as session", () => {
    expect(classifyVolatility({ id: "a", content: "", kind: "memory" })).toBe(
      "session"
    );
    expect(
      classifyVolatility({ id: "a", content: "", kind: "conversation" })
    ).toBe("session");
    expect(classifyVolatility({ id: "a", content: "", kind: "history" })).toBe(
      "session"
    );
  });

  it("classifies query/retrieval/tool-result as request", () => {
    expect(classifyVolatility({ id: "a", content: "", kind: "query" })).toBe(
      "request"
    );
    expect(
      classifyVolatility({ id: "a", content: "", kind: "retrieval" })
    ).toBe("request");
    expect(
      classifyVolatility({ id: "a", content: "", kind: "tool-result" })
    ).toBe("request");
  });

  it("defaults to request for unknown kinds", () => {
    expect(classifyVolatility({ id: "a", content: "", kind: "unknown" })).toBe(
      "request"
    );
    expect(classifyVolatility({ id: "a", content: "" })).toBe("request");
  });

  it("respects explicit volatility in metadata", () => {
    expect(
      classifyVolatility({
        id: "a",
        content: "",
        kind: "query",
        metadata: { volatility: "static" },
      })
    ).toBe("static");
  });
});

describe("packWithCacheTopology", () => {
  it("partitions items into static/session/request", () => {
    const items = [
      makeItem("sys", "system", 10, 100),
      makeItem("mem", "memory", 5, 100),
      makeItem("q", "query", 8, 100),
    ];
    const result = packWithCacheTopology(items, { maxTokens: 500 });
    expect(result.selected).toHaveLength(3);
    expect(result.stats?.staticCount).toBe(1);
    expect(result.stats?.sessionCount).toBe(1);
    expect(result.stats?.requestCount).toBe(1);
  });

  it("orders items as static → session → request", () => {
    const items = [
      makeItem("q", "query", 8, 50),
      makeItem("sys", "system", 10, 50),
      makeItem("mem", "memory", 5, 50),
    ];
    const result = packWithCacheTopology(items, { maxTokens: 500 });
    expect(result.selected[0].id).toBe("sys");
    expect(result.selected[1].id).toBe("mem");
    expect(result.selected[2].id).toBe("q");
  });

  it("sorts static items deterministically by id", () => {
    const items = [
      makeItem("z-tool", "tool", 5, 50),
      makeItem("a-system", "system", 5, 50),
      makeItem("m-schema", "schema", 5, 50),
    ];
    const result = packWithCacheTopology(items, { maxTokens: 500 });
    expect(result.selected[0].id).toBe("a-system");
    expect(result.selected[1].id).toBe("m-schema");
    expect(result.selected[2].id).toBe("z-tool");
  });

  it("produces stable cacheKey for same static items", () => {
    const staticItems = [
      makeItem("sys", "system", 10, 50),
      makeItem("tool", "tool", 8, 50),
    ];

    const r1 = packWithCacheTopology(
      [...staticItems, makeItem("q1", "query", 5, 50)],
      { maxTokens: 500 }
    );
    const r2 = packWithCacheTopology(
      [...staticItems, makeItem("q2", "query", 5, 50)],
      { maxTokens: 500 }
    );

    expect(r1.cacheKey).toBe(r2.cacheKey);
  });

  it("changes cacheKey when static items change", () => {
    const r1 = packWithCacheTopology(
      [makeItem("sys1", "system", 10, 50), makeItem("q", "query", 5, 50)],
      { maxTokens: 500 }
    );
    const r2 = packWithCacheTopology(
      [makeItem("sys2", "system", 10, 50), makeItem("q", "query", 5, 50)],
      { maxTokens: 500 }
    );

    expect(r1.cacheKey).not.toBe(r2.cacheKey);
  });

  it("reports cache efficiency", () => {
    const items = [
      makeItem("sys", "system", 10, 300),
      makeItem("q", "query", 5, 100),
    ];
    const result = packWithCacheTopology(items, { maxTokens: 500 });
    expect(result.cacheableTokens).toBe(300);
    expect(result.volatileTokens).toBe(100);
    expect(result.cacheEfficiency).toBe(0.75);
  });

  it("handles budget constraints", () => {
    const items = [
      makeItem("sys", "system", 10, 200),
      makeItem("mem", "memory", 5, 200),
      makeItem("q", "query", 8, 200),
    ];
    const result = packWithCacheTopology(items, { maxTokens: 400 });
    // Only 400 tokens available, 600 needed — some items dropped
    expect(result.totalTokens).toBeLessThanOrEqual(400);
    expect(result.dropped.length).toBeGreaterThan(0);
  });

  it("adds breakpoint markers when configured", () => {
    const items = [
      makeItem("sys", "system", 10, 50),
      makeItem("mem", "memory", 5, 50),
      makeItem("q", "query", 8, 50),
    ];
    const result = packWithCacheTopology(
      items,
      { maxTokens: 500 },
      {},
      { markBreakpoints: true }
    );
    const staticEnd = result.selected.find(
      i => i.metadata?._cacheBreakpoint === "static-end"
    );
    expect(staticEnd).toBeDefined();
  });

  it("returns empty pack gracefully", () => {
    const result = packWithCacheTopology([], { maxTokens: 500 });
    expect(result.selected).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
    expect(result.cacheEfficiency).toBe(0);
  });

  it("reports partition boundaries", () => {
    const items = [
      makeItem("s1", "system", 10, 50),
      makeItem("s2", "system", 10, 50),
      makeItem("m1", "memory", 5, 50),
      makeItem("q1", "query", 8, 50),
    ];
    const result = packWithCacheTopology(items, { maxTokens: 500 });
    expect(result.partitionBoundaries[0]).toBe(2); // 2 static items
    expect(result.partitionBoundaries[1]).toBe(3); // 2 static + 1 session
  });

  it("scores static items on the same scale as pack (priority-based)", () => {
    // Regression: static items used to be selected without a `score`, so a
    // downstream quality gate (which evicts the lowest `score ?? 0`) would
    // drop high-value cacheable static content first. They must carry their
    // priority-derived score, matching pack()'s default scorer.
    const items = [makeItem("sys", "system", 10, 50)];
    const result = packWithCacheTopology(items, { maxTokens: 500 });

    const staticItem = result.selected.find(i => i.id === "sys");
    expect(staticItem).toBeDefined();
    // Default weights: priority * 1.0 => 10.
    expect(staticItem?.score).toBe(10);
  });
});

describe("packWithCacheTopologyAsync", () => {
  it("produces same structure as sync version", async () => {
    const items = [
      {
        ...createContextItem("sys", "system prompt"),
        metadata: { volatility: "static" },
      },
      {
        ...createContextItem("msg", "user message"),
        metadata: { volatility: "request" },
      },
    ];
    const budget = { maxTokens: 1000 };
    const result = await packWithCacheTopologyAsync(items, budget);
    expect(result.selected).toBeDefined();
    expect(result.cacheKey).toBeDefined();
    expect(result.totalTokens).toBeGreaterThan(0);
  });

  it("returns same results as sync for identical inputs", async () => {
    const items = [
      makeItem("sys", "system", 10, 100),
      makeItem("mem", "memory", 5, 100),
      makeItem("q", "query", 8, 100),
    ];
    const budget = { maxTokens: 500 };

    const syncResult = packWithCacheTopology(items, budget);
    const asyncResult = await packWithCacheTopologyAsync(items, budget);

    expect(asyncResult.selected.map(i => i.id)).toEqual(
      syncResult.selected.map(i => i.id)
    );
    expect(asyncResult.totalTokens).toBe(syncResult.totalTokens);
    expect(asyncResult.cacheKey).toBe(syncResult.cacheKey);
    expect(asyncResult.cacheEfficiency).toBe(syncResult.cacheEfficiency);
  });

  it("handles empty items gracefully", async () => {
    const result = await packWithCacheTopologyAsync([], { maxTokens: 500 });
    expect(result.selected).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
    expect(result.cacheEfficiency).toBe(0);
  });
});

describe("packWithCacheTopology — P1 regressions", () => {
  function assertPartition(
    input: ContextItem[],
    result: { selected: ContextItem[]; dropped: ContextItem[] }
  ) {
    // Every input item ends up in exactly one of selected/dropped.
    expect(result.selected.length + result.dropped.length).toBe(input.length);
    const selectedIds = result.selected.map(i => i.id).sort();
    const droppedIds = result.dropped.map(i => i.id).sort();
    expect([...selectedIds, ...droppedIds].sort()).toEqual(
      input.map(i => i.id).sort()
    );
  }

  it("classifies an invalid metadata.volatility as request instead of dropping the item", () => {
    const item: ContextItem = {
      id: "typo",
      content: "x",
      tokens: 5,
      metadata: { volatility: "typo" },
    };
    expect(classifyVolatility(item)).toBe("request");
    const result = packWithCacheTopology([item], { maxTokens: 100 });
    expect(result.selected.map(i => i.id)).toEqual(["typo"]);
    assertPartition([item], result);
  });

  it("ignores non-string metadata.volatility values", () => {
    expect(
      classifyVolatility({
        id: "a",
        content: "",
        kind: "system",
        metadata: { volatility: 42 },
      })
    ).toBe("static");
  });

  it("rejects reserveTokens >= maxTokens like pack()", () => {
    const items = [makeItem("s", "system", 1, 10)];
    expect(() =>
      packWithCacheTopology(items, { maxTokens: 100, reserveTokens: 100 })
    ).toThrow(/reserveTokens/);
  });

  it("rejects a non-positive maxTokens like pack()", () => {
    const items = [makeItem("s", "system", 1, 10)];
    expect(() => packWithCacheTopology(items, { maxTokens: 0 })).toThrow(
      /maxTokens/
    );
  });

  it("rejects invalid budgets on the async path", async () => {
    await expect(
      packWithCacheTopologyAsync([], { maxTokens: 10, reserveTokens: 20 })
    ).rejects.toThrow(/reserveTokens/);
  });

  it("keeps an unselected static item in dropped even if a selected one shares its id", () => {
    const items = [
      { id: "dup", content: "small", kind: "system", tokens: 10 },
      { id: "dup", content: "big", kind: "system", tokens: 1000 },
    ];
    const result = packWithCacheTopology(items, { maxTokens: 100 });
    expect(result.selected).toHaveLength(1);
    expect(result.dropped).toHaveLength(1);
    expect(result.dropped[0].content).toBe("big");
    assertPartition(items, result);
  });

  it("reports zero cacheable tokens when the static prefix is below minPrefixTokens", () => {
    const items = [
      makeItem("sys", "system", 10, 100),
      makeItem("q", "query", 5, 50),
    ];
    const result = packWithCacheTopology(
      items,
      { maxTokens: 1000 },
      {},
      { minPrefixTokens: 200 }
    );
    expect(result.totalTokens).toBe(150);
    expect(result.cacheableTokens).toBe(0);
    expect(result.cacheEfficiency).toBe(0);
    expect(result.volatileTokens).toBe(150);
  });

  it("reports cacheable tokens when the static prefix meets minPrefixTokens", () => {
    const items = [makeItem("sys", "system", 10, 200)];
    const result = packWithCacheTopology(
      items,
      { maxTokens: 1000 },
      {},
      { minPrefixTokens: 200 }
    );
    expect(result.cacheableTokens).toBe(200);
    expect(result.cacheEfficiency).toBe(1);
  });

  it("never exceeds the effective budget and does not mutate inputs", () => {
    const items = [
      makeItem("s1", "system", 9, 40),
      makeItem("s2", "system", 3, 40),
      makeItem("m1", "memory", 5, 30),
      makeItem("m2", "memory", 2, 30),
      makeItem("q1", "query", 8, 25),
      makeItem("r1", "retrieval", 1, 25),
    ];
    const snapshot = JSON.parse(JSON.stringify(items));
    const budget = { maxTokens: 150, reserveTokens: 20 };
    const result = packWithCacheTopology(
      items,
      budget,
      {},
      { markBreakpoints: true }
    );
    expect(result.totalTokens).toBeLessThanOrEqual(130);
    assertPartition(items, result);
    expect(items).toEqual(snapshot);
  });
});
