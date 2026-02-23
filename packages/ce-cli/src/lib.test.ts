import { describe, expect, it } from "vitest";
import {
  runPack,
  runDiff,
  runBudget,
  lintFile,
  runTrace,
  loadItemsFromFile,
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
