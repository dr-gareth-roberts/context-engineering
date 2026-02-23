import { describe, expect, it } from "vitest";
import {
  runPack,
  runDiff,
  runBudget,
  lintFile,
  runTrace,
  loadItemsFromFile,
  runPlace,
  runQuality,
  runEffectiveBudget,
  runHandoff,
  runPickup,
  runCost,
} from "./lib.js";
import { promises as fs } from "fs";
import os from "os";
import path from "path";

const items = [
  { id: "x", content: "Alpha", tokens: 10, priority: 2 },
  { id: "y", content: "Beta", tokens: 20, priority: 1 },
];

describe("runPack", () => {
  it("packs items within budget", () => {
    const result = runPack(items, 15);
    expect(result.selected.length).toBe(1);
    expect(result.selected[0].id).toBe("x");
  });

  it("packs all items when budget is large", () => {
    const result = runPack(items, 1000);
    expect(result.selected.length).toBe(2);
  });

  it("returns empty pack for zero items", () => {
    const result = runPack([], 100);
    expect(result.selected.length).toBe(0);
  });

  it("supports openai provider", () => {
    const result = runPack(items, 1000, { provider: "openai" });
    expect(result.selected.length).toBeGreaterThan(0);
  });

  it("supports anthropic provider", () => {
    const result = runPack(items, 1000, { provider: "anthropic" });
    expect(result.selected.length).toBeGreaterThan(0);
  });
});

describe("runDiff", () => {
  it("detects removals", () => {
    const d = runDiff(items, [items[0]]);
    expect(d.removed.length).toBe(1);
    expect(d.removed[0].id).toBe("y");
  });

  it("handles identical inputs", () => {
    const d = runDiff(items, [...items]);
    expect(d.added.length).toBe(0);
    expect(d.removed.length).toBe(0);
  });
});

describe("runBudget", () => {
  it("estimates tokens for text", () => {
    const tokens = runBudget("hello world");
    expect(tokens).toBeGreaterThan(0);
  });

  it("estimates with openai provider", () => {
    const tokens = runBudget("hello world", { provider: "openai" });
    expect(tokens).toBeGreaterThan(0);
  });
});

describe("runTrace", () => {
  it("returns trace steps", () => {
    const trace = runTrace(items, 15);
    expect(trace.steps.length).toBeGreaterThan(0);
  });

  it("trace has createdAt", () => {
    const trace = runTrace(items, 15);
    expect(trace.createdAt).toBeDefined();
  });
});

describe("lintFile", () => {
  it("validates valid context item", async () => {
    const result = await lintFile("context-item", { id: "z", content: "test" });
    expect(result.valid).toBe(true);
  });

  it("rejects invalid context item", async () => {
    const result = await lintFile("context-item", { notAnId: true });
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it("throws for unknown schema", async () => {
    await expect(lintFile("nonexistent" as any, {})).rejects.toThrow();
  });
});

describe("loadItemsFromFile", () => {
  const tempDir = path.join(os.tmpdir(), `ce-cli-tests-${Date.now()}`);

  it("loads JSON array", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "items.json");
    await fs.writeFile(filePath, JSON.stringify(items));
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded.length).toBe(2);
  });

  it("loads JSON object with items field", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "wrapped.json");
    await fs.writeFile(filePath, JSON.stringify({ items }));
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded.length).toBe(2);
  });

  it("loads JSONL", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "items.jsonl");
    const content = items.map(i => JSON.stringify(i)).join("\n");
    await fs.writeFile(filePath, content);
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded.length).toBe(2);
  });

  it("returns empty array for empty file", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "empty.json");
    await fs.writeFile(filePath, "");
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded).toEqual([]);
  });

  it("throws for nonexistent file", async () => {
    await expect(loadItemsFromFile("/nonexistent/path.json")).rejects.toThrow();
  });
});

// ─── New command tests ────────────────────────────────────────────────

const richItems = [
  { id: "sys", content: "You are a helpful assistant.", kind: "system", priority: 10, recency: 3, tokens: 10 },
  { id: "doc1", content: "Document about context engineering and token budgets.", kind: "retrieval", priority: 7, recency: 8, tokens: 15 },
  { id: "doc2", content: "Another document about context engineering and packing.", kind: "retrieval", priority: 6, recency: 7, tokens: 15 },
  { id: "query", content: "How does packing work?", kind: "query", priority: 8, recency: 10, tokens: 8 },
];

describe("runPlace", () => {
  it("places items with attention-optimized strategy", () => {
    const result = runPlace(richItems, 1000, { strategy: "attention-optimized" });
    expect(result.selected.length).toBe(4);
    expect(result.strategy).toBe("attention-optimized");
    expect(result.totalTokens).toBeGreaterThan(0);
  });

  it("places items with score-order strategy", () => {
    const result = runPlace(richItems, 1000, { strategy: "score-order" });
    expect(result.selected.length).toBe(4);
    expect(result.strategy).toBe("score-order");
  });

  it("respects budget constraint", () => {
    const result = runPlace(richItems, 20);
    expect(result.totalTokens).toBeLessThanOrEqual(20);
  });

  it("supports model parameter", () => {
    const result = runPlace(richItems, 1000, { model: "claude" });
    expect(result.selected.length).toBe(4);
  });
});

describe("runQuality", () => {
  it("returns quality metrics", () => {
    const quality = runQuality(richItems, 1000);
    expect(quality.itemCount).toBe(4);
    expect(quality.totalTokens).toBeGreaterThan(0);
    expect(quality.density).toBeGreaterThanOrEqual(0);
    expect(quality.diversity).toBeGreaterThanOrEqual(0);
    expect(quality.overall).toBeGreaterThan(0);
  });

  it("returns zero metrics for empty input", () => {
    const quality = runQuality([], 1000);
    expect(quality.itemCount).toBe(0);
    expect(quality.overall).toBe(0);
  });

  it("detects redundancy in similar items", () => {
    const similar = [
      { id: "a", content: "context engineering toolkit pack tokens budget", tokens: 10, priority: 5 },
      { id: "b", content: "context engineering toolkit pack tokens budget", tokens: 10, priority: 5 },
    ];
    const quality = runQuality(similar, 1000);
    expect(quality.redundancy).toBeGreaterThan(0.5);
  });
});

describe("runEffectiveBudget", () => {
  it("calculates effective budget for default model", () => {
    const result = runEffectiveBudget(200000);
    expect(result.advertised).toBe(200000);
    expect(result.effective).toBeLessThan(200000);
    expect(result.effective).toBeGreaterThan(0);
    expect(result.model).toBe("default");
    expect(result.ratio).toBeLessThan(1);
  });

  it("calculates effective budget for claude", () => {
    const result = runEffectiveBudget(200000, "claude");
    expect(result.model).toBe("claude");
    expect(result.effective).toBe(140000); // 70% capacity
  });

  it("calculates effective budget for gpt4", () => {
    const result = runEffectiveBudget(128000, "gpt4");
    expect(result.model).toBe("gpt4");
    expect(result.effective).toBe(83200); // 65% capacity
  });
});

describe("runHandoff", () => {
  it("creates BEADS JSONL from items", () => {
    const result = runHandoff(richItems, 1000);
    expect(result.jsonl).toBeTruthy();
    expect(result.issues.length).toBeGreaterThan(0);
    expect(result.stats.activeItems).toBe(4);
    expect(result.stats.totalIssues).toBe(5); // 4 items + 1 manifest
  });

  it("includes dropped items when requested", () => {
    const result = runHandoff(richItems, 20, { includeDropped: true });
    expect(result.stats.deferredItems).toBeGreaterThan(0);
  });

  it("sets agent identity", () => {
    const result = runHandoff(richItems, 1000, { agent: "agent-1" });
    const manifest = result.issues[0];
    expect(manifest.assignee).toBe("agent-1");
  });

  it("supports cache topology mode", () => {
    const result = runHandoff(richItems, 1000, { cacheTopology: true });
    expect(result.stats.activeItems).toBe(4);
  });
});

describe("runPickup", () => {
  it("recovers items from handoff JSONL", () => {
    const handoff = runHandoff(richItems, 1000);
    const pickup = runPickup(handoff.jsonl);
    expect(pickup.items.length).toBe(4);
    expect(pickup.manifest).not.toBeNull();
    expect(pickup.stats.contextItems).toBe(4);
  });

  it("recovers deferred items", () => {
    const handoff = runHandoff(richItems, 20, { includeDropped: true });
    const pickup = runPickup(handoff.jsonl);
    expect(pickup.deferred.length).toBeGreaterThan(0);
  });

  it("roundtrips item IDs correctly", () => {
    const handoff = runHandoff(richItems, 1000);
    const pickup = runPickup(handoff.jsonl);
    const recoveredIds = pickup.items.map(i => i.id).sort();
    const originalIds = richItems.map(i => i.id).sort();
    expect(recoveredIds).toEqual(originalIds);
  });
});

describe("runCost", () => {
  it("estimates cost for claude-sonnet-4-6", () => {
    const { estimate } = runCost(richItems, 1000, "claude-sonnet-4-6");
    expect(estimate.model).toBe("claude-sonnet-4-6");
    expect(estimate.inputTokens).toBeGreaterThan(0);
    expect(estimate.costWithoutCache).toBeGreaterThan(0);
    expect(estimate.costWithCache).toBeGreaterThanOrEqual(0);
  });

  it("estimates cost for claude-opus-4-6", () => {
    const { estimate } = runCost(richItems, 1000, "claude-opus-4-6");
    expect(estimate.costWithoutCache).toBeGreaterThan(0);
  });

  it("includes projection when requestCount specified", () => {
    const { estimate, projection } = runCost(richItems, 1000, "claude-sonnet-4-6", {
      requestCount: 1000,
    });
    expect(projection).toBeDefined();
    expect(projection!.requestCount).toBe(1000);
    expect(projection!.totalWithoutCache).toBeGreaterThan(0);
  });

  it("includes monthly estimate when requestsPerDay specified", () => {
    const { projection } = runCost(richItems, 1000, "claude-sonnet-4-6", {
      requestCount: 1000,
      requestsPerDay: 500,
    });
    expect(projection!.monthlyEstimate).toBeDefined();
    expect(projection!.monthlyEstimate!.requestsPerDay).toBe(500);
    expect(projection!.monthlyEstimate!.monthlyCostWithoutCache).toBeGreaterThan(0);
  });

  it("throws for unknown model", () => {
    expect(() => runCost(richItems, 1000, "unknown-model")).toThrow(/Unknown model/);
  });
});
