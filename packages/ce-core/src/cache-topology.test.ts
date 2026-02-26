import { describe, expect, it } from "vitest";
import { classifyVolatility, packWithCacheTopology } from "./cache-topology.js";
import type { ContextItem } from "./types.js";

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
});
