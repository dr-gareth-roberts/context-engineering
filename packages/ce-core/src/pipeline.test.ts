import { describe, expect, it } from "vitest";
import { pipeline, ContextPipeline } from "./pipeline.js";
import { createSession } from "./session.js";
import { createContextItem } from "./types.js";
import type { ContextItem, MemoryItem } from "./types.js";

function makeItem(
  id: string,
  kind: string,
  priority: number,
  tokens: number
): ContextItem {
  return { id, content: `content-${id}`, kind, priority, tokens };
}

describe("pipeline", () => {
  it("creates a pipeline with numeric budget", () => {
    const result = pipeline(500)
      .add(makeItem("a", "system", 10, 50))
      .build();

    expect(result.selected).toHaveLength(1);
    expect(result.totalTokens).toBe(50);
    expect(result.budget.maxTokens).toBe(500);
  });

  it("creates a pipeline with Budget object", () => {
    const result = pipeline({ maxTokens: 500 })
      .add(makeItem("a", "system", 10, 50))
      .build();

    expect(result.selected).toHaveLength(1);
  });

  it("adds multiple items", () => {
    const result = pipeline(500)
      .add(makeItem("a", "system", 10, 50), makeItem("b", "retrieval", 7, 50))
      .build();

    expect(result.selected).toHaveLength(2);
    expect(result.inputCount).toBe(2);
  });

  it("addMany applies defaults", () => {
    const items = [
      { id: "r1", content: "doc 1", tokens: 50 },
      { id: "r2", content: "doc 2", tokens: 50 },
    ] as ContextItem[];

    const result = pipeline(500)
      .addMany(items, { kind: "retrieval", priority: 5 })
      .build();

    expect(result.selected).toHaveLength(2);
    expect(result.selected[0].kind).toBe("retrieval");
  });

  it("respects budget constraints", () => {
    const result = pipeline(100)
      .add(makeItem("a", "system", 10, 60), makeItem("b", "retrieval", 5, 60))
      .build();

    expect(result.totalTokens).toBeLessThanOrEqual(100);
    expect(result.dropped.length).toBeGreaterThan(0);
  });

  it("applies allocation", () => {
    const result = pipeline(300)
      .add(
        makeItem("s", "system", 10, 50),
        makeItem("r1", "retrieval", 7, 100),
        makeItem("r2", "retrieval", 6, 100)
      )
      .allocate([
        { kind: "system", targetRatio: 0.3 },
        { kind: "retrieval", targetRatio: 0.7 },
      ])
      .build();

    expect(result.stages).toContain("allocate");
    expect(result.allocations).toBeDefined();
    expect(result.allocationEfficiency).toBeDefined();
  });

  it("applies cache topology", () => {
    const result = pipeline(500)
      .add(makeItem("sys", "system", 10, 100), makeItem("q", "query", 8, 50))
      .cacheTopology({ provider: "anthropic" })
      .build();

    expect(result.stages).toContain("cacheTopology");
    expect(result.cacheKey).toBeDefined();
    expect(result.cacheEfficiency).toBeDefined();
    expect(result.cacheableTokens).toBeDefined();
  });

  it("cache topology orders static before request", () => {
    const result = pipeline(500)
      .add(makeItem("q", "query", 8, 50), makeItem("sys", "system", 10, 50))
      .cacheTopology()
      .build();

    expect(result.selected[0].id).toBe("sys");
    expect(result.selected[1].id).toBe("q");
  });

  it("applies placement", () => {
    const result = pipeline(500)
      .add(
        makeItem("a", "system", 10, 50),
        makeItem("b", "retrieval", 7, 50),
        makeItem("c", "query", 5, 50)
      )
      .place("score-order")
      .build();

    expect(result.stages).toContain("place");
    expect(result.selected).toHaveLength(3);
  });

  it("applies quality gate", () => {
    const result = pipeline(500)
      .add(makeItem("a", "system", 10, 100), makeItem("b", "retrieval", 7, 100))
      .qualityGate({ minOverall: 0.0 }) // permissive gate
      .build();

    expect(result.stages).toContain("quality");
    expect(result.quality).toBeDefined();
    expect(result.quality!.overall).toBeGreaterThan(0);
  });

  it("applies session tracking", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    // First build
    const r1 = pipeline(500)
      .add(makeItem("a", "system", 10, 50))
      .session(session)
      .build();

    expect(r1.stages).toContain("session");
    expect(r1.delta).toBeNull(); // first compile

    // Second build with same session
    const r2 = pipeline(500)
      .add(makeItem("a", "system", 10, 50))
      .session(session)
      .build();

    expect(r2.delta).not.toBeNull();
    expect(r2.delta!.keptCount).toBe(1);
    expect(r2.delta!.reuseRatio).toBe(1);
  });

  it("combines allocation + cache topology", () => {
    const result = pipeline(500)
      .add(
        makeItem("sys", "system", 10, 100),
        makeItem("mem", "memory", 5, 100),
        makeItem("q", "query", 8, 50)
      )
      .allocate([
        { kind: "system", targetRatio: 0.4 },
        { kind: "memory", targetRatio: 0.3 },
        { kind: "query", targetRatio: 0.3 },
      ])
      .cacheTopology()
      .build();

    expect(result.stages).toContain("allocate");
    expect(result.stages).toContain("cacheTopology");
    expect(result.cacheKey).toBeDefined();
    expect(result.allocations).toBeDefined();
  });

  it("full pipeline with all stages", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    const result = pipeline(500)
      .add(
        makeItem("sys", "system", 10, 100),
        makeItem("mem", "memory", 5, 80),
        makeItem("doc", "retrieval", 7, 80),
        makeItem("q", "query", 8, 50)
      )
      .allocate([
        { kind: "system", targetRatio: 0.3 },
        { kind: "memory", targetRatio: 0.2 },
        { kind: "retrieval", targetRatio: 0.3 },
        { kind: "query", targetRatio: 0.2 },
      ])
      .cacheTopology({ provider: "anthropic" })
      .place("score-order")
      .qualityGate()
      .session(session)
      .build();

    expect(result.selected.length).toBeGreaterThan(0);
    expect(result.stages).toContain("allocate");
    expect(result.stages).toContain("cacheTopology");
    expect(result.stages).toContain("place");
    expect(result.stages).toContain("quality");
    expect(result.stages).toContain("session");
    expect(result.quality).toBeDefined();
    expect(result.cacheKey).toBeDefined();
    expect(result.delta).toBeNull(); // first compile
  });

  it("handles empty pipeline", () => {
    const result = pipeline(500).build();

    expect(result.selected).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
    expect(result.inputCount).toBe(0);
  });

  it("addMemories bridges memory items", () => {
    const memories: MemoryItem[] = [
      {
        id: "m1",
        content: "I like TypeScript",
        createdAt: new Date().toISOString(),
      },
      { id: "m2", content: "I use React", createdAt: new Date().toISOString() },
    ];

    const result = pipeline(500)
      .addMemories(memories, { kind: "memory" })
      .build();

    expect(result.selected.length).toBeGreaterThanOrEqual(2);
    expect(result.stages).toContain("bridge");
  });

  it("weights affect scoring", () => {
    const r1 = pipeline(100)
      .add(makeItem("a", "system", 10, 80), makeItem("b", "retrieval", 3, 80))
      .weights({ priority: 1.0, recency: 0.0 })
      .build();

    // With high priority weight, 'a' (priority 10) should be selected
    expect(r1.selected[0].id).toBe("a");
  });

  it("records stages applied", () => {
    const result = pipeline(500)
      .add(makeItem("a", "system", 10, 50))
      .cacheTopology()
      .qualityGate()
      .build();

    expect(result.stages).toContain("cacheTopology");
    expect(result.stages).toContain("quality");
    expect(result.stages).not.toContain("allocate");
    expect(result.stages).not.toContain("session");
  });
});

describe("pipeline withQuery", () => {
  it("withQuery changes selection order based on relevance", () => {
    const result = pipeline(1000)
      .add(
        createContextItem("irrelevant", "unrelated xyz content", {
          priority: 5,
          tokens: 50,
        }),
        createContextItem("relevant", "machine learning algorithms", {
          priority: 5,
          tokens: 50,
        })
      )
      .withQuery("machine learning")
      .build();

    expect(result.selected[0].id).toBe("relevant");
    expect(result.stages).toContain("query");
  });

  it("stages includes 'query' when withQuery is used", () => {
    const result = pipeline(1000)
      .add(createContextItem("a", "content", { priority: 5, tokens: 50 }))
      .withQuery("test")
      .build();

    expect(result.stages).toContain("query");
  });
});

describe("pipeline template", () => {
  it("template produces messages on result", () => {
    const result = pipeline(1000)
      .add(
        createContextItem("sys", "system prompt", {
          kind: "system",
          priority: 10,
          tokens: 50,
        }),
        createContextItem("q", "user question", {
          kind: "query",
          priority: 5,
          tokens: 50,
        })
      )
      .template()
      .build();

    expect(result.messages).toBeDefined();
    expect(result.messages!.messages.length).toBeGreaterThan(0);
    expect(result.stages).toContain("template");
  });

  it("template messages have correct roles", () => {
    const result = pipeline(1000)
      .add(
        createContextItem("sys", "system prompt", {
          kind: "system",
          priority: 10,
          tokens: 50,
        }),
        createContextItem("q", "user question", {
          kind: "query",
          priority: 5,
          tokens: 50,
        })
      )
      .template()
      .build();

    const systemMsgs = result.messages!.messages.filter(
      m => m.role === "system"
    );
    const userMsgs = result.messages!.messages.filter(m => m.role === "user");
    expect(systemMsgs.length).toBeGreaterThan(0);
    expect(userMsgs.length).toBeGreaterThan(0);
  });

  it("without template, messages is undefined", () => {
    const result = pipeline(1000)
      .add(createContextItem("a", "content", { priority: 5, tokens: 50 }))
      .build();

    expect(result.messages).toBeUndefined();
  });

  it("buildAsync supports allocation", async () => {
    const result = await pipeline(500)
      .add(makeItem("s1", "system", 10, 50))
      .add(makeItem("r1", "retrieval", 5, 100))
      .add(makeItem("r2", "retrieval", 3, 100))
      .allocate([
        { kind: "system", targetRatio: 0.2, minTokens: 50 },
        { kind: "retrieval", targetRatio: 0.8 },
      ])
      .buildAsync();

    expect(result.stages).toContain("allocate");
    expect(result.allocationEfficiency).toBeDefined();
    expect(result.totalTokens).toBeLessThanOrEqual(500);
  });

  it("buildAsync supports cache topology", async () => {
    const result = await pipeline(500)
      .add(makeItem("s1", "system", 10, 50))
      .add(makeItem("r1", "retrieval", 5, 100))
      .cacheTopology({ provider: "anthropic" })
      .buildAsync();

    expect(result.stages).toContain("cacheTopology");
    expect(result.cacheKey).toBeDefined();
    expect(result.cacheEfficiency).toBeDefined();
  });

  it("buildAsync supports template", async () => {
    const result = await pipeline(1000)
      .add(
        createContextItem("a", "content", {
          priority: 5,
          tokens: 50,
          kind: "system",
        })
      )
      .template({ systemPrefix: "You are a helper." })
      .buildAsync();

    expect(result.stages).toContain("template");
    expect(result.messages).toBeDefined();
  });

  it("buildAsync with allocation + cache topology combined", async () => {
    const result = await pipeline(500)
      .add(makeItem("s1", "system", 10, 50))
      .add(makeItem("r1", "retrieval", 5, 100))
      .allocate([
        { kind: "system", targetRatio: 0.2, minTokens: 50 },
        { kind: "retrieval", targetRatio: 0.8 },
      ])
      .cacheTopology()
      .buildAsync();

    expect(result.stages).toContain("allocate");
    expect(result.stages).toContain("cacheTopology");
    expect(result.cacheKey).toBeDefined();
    expect(result.allocationEfficiency).toBeDefined();
  });
});
