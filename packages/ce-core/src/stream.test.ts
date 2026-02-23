import { describe, expect, it } from "vitest";
import { packStream } from "./stream.js";
import type { ContextItem } from "./types.js";

const items: ContextItem[] = [
  { id: "a", content: "High priority", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 },
];

describe("packStream", () => {
  it("yields selected items one by one", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream(items, { maxTokens: 200 })) {
      selected.push(item);
    }
    expect(selected.length).toBe(3);
  });

  it("respects budget", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream(items, { maxTokens: 55 })) {
      selected.push(item);
    }
    const totalTokens = selected.reduce((sum, i) => sum + (i.tokens ?? 0), 0);
    expect(totalTokens).toBeLessThanOrEqual(55);
  });

  it("yields items in score order", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream(items, { maxTokens: 200 })) {
      selected.push(item);
    }
    expect(selected[0].id).toBe("a");
  });

  it("validates budget", async () => {
    const gen = packStream(items, { maxTokens: -1 });
    await expect(gen.next()).rejects.toThrow();
  });

  it("yields nothing for empty items", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream([], { maxTokens: 100 })) {
      selected.push(item);
    }
    expect(selected.length).toBe(0);
  });

  it("drops items with compressions instead of compressing them", async () => {
    const compressibleItems: ContextItem[] = [
      {
        id: "big",
        content: "Large content",
        priority: 10,
        tokens: 200,
        compressions: [{ content: "Small", tokens: 20, note: "summary" }],
      },
    ];
    const selected: ContextItem[] = [];
    for await (const item of packStream(compressibleItems, { maxTokens: 50 })) {
      selected.push(item);
    }
    // packStream does not apply compressions — items that exceed budget are simply skipped
    expect(selected.length).toBe(0);
  });
});
