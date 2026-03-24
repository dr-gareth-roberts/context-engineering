import { describe, it, expect } from "vitest";
import { createContextCompiler } from "../compiler.js";
import { contextProgram } from "../program.js";
import type { ContextItem } from "@context-engineering/core";

function item(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return {
    id,
    content,
    tokens: Math.ceil(content.split(/\s+/).length * 1.3),
    ...overrides,
  };
}

describe("createContextCompiler", () => {
  it("compiles a simple program with matching items", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("system", { kind: "system", required: true, position: "first" })
      .declare("code", { kind: "code" })
      .constraint("coverage")
      .build();

    const items = [
      item("sys1", "You are a helpful assistant", {
        kind: "system",
        tokens: 10,
      }),
      item("code1", "function hello() { return 1; }", {
        kind: "code",
        tokens: 15,
      }),
    ];

    const result = compiler.compile(program, {
      target: "claude",
      items,
      budget: { maxTokens: 1000 },
    });

    expect(result.items.length).toBeGreaterThan(0);
    expect(result.target).toBe("claude");
    expect(result.totalTokens).toBeGreaterThan(0);
    expect(result.quality).toBeDefined();
    expect(result.optimizations.length).toBeGreaterThan(0);
  });

  it("drops items that exceed budget", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const items = [
      item("a", "first item", { kind: "code", tokens: 50 }),
      item("b", "second item", { kind: "code", tokens: 50 }),
      item("c", "third item", { kind: "code", tokens: 50 }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 100 },
    });

    expect(result.items.length).toBeLessThan(3);
    expect(result.dropped.length).toBeGreaterThan(0);
    expect(result.totalTokens).toBeLessThanOrEqual(100);
  });

  it("generates error diagnostics for unsatisfied required slots", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("system", { kind: "system", required: true })
      .declare("code", { kind: "code" })
      .build();

    const items = [item("code1", "some code", { kind: "code", tokens: 10 })];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    const errors = result.diagnostics.filter(d => d.level === "error");
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some(d => d.slot === "system")).toBe(true);
  });

  it("fillRemaining slots get leftover budget", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("system", { kind: "system", maxTokens: 100 })
      .declare("extra", { kind: "extra", fillRemaining: true })
      .build();

    const items = [
      item("sys1", "system prompt", { kind: "system", tokens: 50 }),
      item("extra1", "extra content a", { kind: "extra", tokens: 200 }),
      item("extra2", "extra content b", { kind: "extra", tokens: 200 }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 500 },
    });

    expect(result.slots["system"].tokensUsed).toBe(50);
    expect(result.slots["extra"].tokensUsed).toBeGreaterThan(0);
    expect(result.slots["extra"].tokensUsed).toBeLessThanOrEqual(450);
  });

  it("respects position constraints in output", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("system", { kind: "system", position: "first" })
      .declare("code", { kind: "code" })
      .declare("history", { kind: "history", position: "last" })
      .build();

    const items = [
      item("hist1", "conversation history", { kind: "history", tokens: 20 }),
      item("code1", "function code block", { kind: "code", tokens: 20 }),
      item("sys1", "system instructions", { kind: "system", tokens: 20 }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    // System should be first, history should be last
    const firstItem = result.items[0];
    const lastItem = result.items[result.items.length - 1];
    expect(firstItem.kind).toBe("system");
    expect(lastItem.kind).toBe("history");
  });

  it("selects items by priority strategy", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("code", { kind: "code", strategy: "priority", maxTokens: 100 })
      .build();

    const items = [
      item("low", "low priority code", {
        kind: "code",
        priority: 1,
        tokens: 40,
      }),
      item("high", "high priority code", {
        kind: "code",
        priority: 10,
        tokens: 40,
      }),
      item("med", "medium priority code", {
        kind: "code",
        priority: 5,
        tokens: 40,
      }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 100 },
    });

    // Should include the highest priority items within budget
    const selectedIds = result.items.map(i => i.id);
    expect(selectedIds).toContain("high");
    expect(selectedIds).toContain("med");
    // low should be dropped due to budget
    expect(result.dropped.some(d => d.id === "low")).toBe(true);
  });

  it("selects items by recency strategy", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("history", {
        kind: "history",
        strategy: "recency",
        maxTokens: 60,
      })
      .build();

    const items = [
      item("old", "old history entry", {
        kind: "history",
        recency: 1,
        tokens: 30,
      }),
      item("new", "new history entry", {
        kind: "history",
        recency: 9,
        tokens: 30,
      }),
      item("mid", "mid history entry", {
        kind: "history",
        recency: 5,
        tokens: 30,
      }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    const selectedIds = result.items.map(i => i.id);
    expect(selectedIds).toContain("new");
    expect(selectedIds).toContain("mid");
  });

  it("selects items by relevance strategy", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("docs", { kind: "docs", strategy: "relevance", maxTokens: 60 })
      .build();

    const items = [
      item("low", "low relevance doc", {
        kind: "docs",
        score: 0.1,
        tokens: 30,
      }),
      item("high", "high relevance doc", {
        kind: "docs",
        score: 0.9,
        tokens: 30,
      }),
      item("mid", "mid relevance doc", {
        kind: "docs",
        score: 0.5,
        tokens: 30,
      }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    const selectedIds = result.items.map(i => i.id);
    expect(selectedIds).toContain("high");
    expect(selectedIds).toContain("mid");
  });

  it("handles empty items gracefully", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const result = compiler.compile(program, {
      target: "generic",
      items: [],
      budget: { maxTokens: 1000 },
    });

    expect(result.items).toHaveLength(0);
    expect(result.dropped).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
  });

  it("handles items with no matching slots", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const items = [
      item("a", "orphan item with unknown kind", {
        kind: "unknown",
        tokens: 10,
      }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    // Uncategorized items should be dropped (no fillRemaining slot)
    expect(result.dropped).toHaveLength(1);
    expect(result.dropped[0].id).toBe("a");
  });

  it("uncategorized items go to fillRemaining slots", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("code", { kind: "code" })
      .declare("overflow", { kind: "overflow", fillRemaining: true })
      .build();

    const items = [
      item("a", "unknown kind item", { kind: "unknown", tokens: 10 }),
      item("b", "code item", { kind: "code", tokens: 10 }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    const selectedIds = result.items.map(i => i.id);
    expect(selectedIds).toContain("a");
    expect(selectedIds).toContain("b");
  });

  it("all items dropped when budget is zero", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const items = [item("a", "some content", { kind: "code", tokens: 10 })];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 0 },
    });

    expect(result.items).toHaveLength(0);
    expect(result.dropped).toHaveLength(1);
  });

  it("respects reserveTokens in budget", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const items = [
      item("a", "content a", { kind: "code", tokens: 50 }),
      item("b", "content b", { kind: "code", tokens: 50 }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 120, reserveTokens: 40 },
    });

    // Effective budget is 80 tokens, so only one item should fit
    expect(result.items).toHaveLength(1);
    expect(result.totalTokens).toBeLessThanOrEqual(80);
  });

  it("returns slot breakdown", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("system", { kind: "system" })
      .declare("code", { kind: "code" })
      .build();

    const items = [
      item("sys1", "system prompt here", { kind: "system", tokens: 20 }),
      item("code1", "code block here", { kind: "code", tokens: 30 }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    expect(result.slots["system"]).toBeDefined();
    expect(result.slots["system"].itemCount).toBe(1);
    expect(result.slots["system"].tokensUsed).toBe(20);
    expect(result.slots["code"]).toBeDefined();
    expect(result.slots["code"].itemCount).toBe(1);
    expect(result.slots["code"].tokensUsed).toBe(30);
  });

  it("validates constraints in compiled output", () => {
    const compiler = createContextCompiler();
    const program = contextProgram()
      .declare("data", { kind: "data" })
      .constraint("budget-utilization", { threshold: 0.7 })
      .build();

    const items = [item("a", "tiny item", { kind: "data", tokens: 10 })];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 10000 },
    });

    const budgetDiags = result.diagnostics.filter(
      d => d.constraint === "budget-utilization"
    );
    expect(budgetDiags.length).toBeGreaterThan(0);
  });

  it("computes quality metrics", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const items = [
      item("a", "typescript strict mode configuration settings", {
        kind: "code",
        tokens: 10,
        recency: 8,
      }),
      item("b", "python testing framework pytest setup", {
        kind: "code",
        tokens: 10,
        recency: 7,
      }),
    ];

    const result = compiler.compile(program, {
      target: "generic",
      items,
      budget: { maxTokens: 1000 },
    });

    expect(result.quality).toBeDefined();
    expect(result.quality.itemCount).toBe(2);
    expect(result.quality.overall).toBeGreaterThan(0);
  });

  it("different targets produce different results", () => {
    const compiler = createContextCompiler();
    const program = contextProgram().declare("code", { kind: "code" }).build();

    const items = Array.from({ length: 5 }, (_, i) =>
      item(`item-${i}`, `content number ${i} with some words`, {
        kind: "code",
        priority: i * 3,
        tokens: 20,
      })
    );

    const claudeResult = compiler.compile(program, {
      target: "claude",
      items,
      budget: { maxTokens: 1000 },
    });

    const gptResult = compiler.compile(program, {
      target: "gpt4",
      items,
      budget: { maxTokens: 1000 },
    });

    expect(claudeResult.target).toBe("claude");
    expect(gptResult.target).toBe("gpt4");

    // The ordering should differ
    const claudeIds = claudeResult.items.map(i => i.id);
    const gptIds = gptResult.items.map(i => i.id);
    expect(claudeIds).not.toEqual(gptIds);
  });
});
