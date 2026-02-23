import { describe, expect, it } from "vitest";
import { tracePack } from "./trace.js";
import type { ContextItem } from "./types.js";

const items: ContextItem[] = [
  { id: "a", content: "High", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 },
];

describe("tracePack", () => {
  it("records include decisions", () => {
    const trace = tracePack(items, { maxTokens: 200 });
    expect(trace.steps.length).toBe(3);
    expect(trace.steps.every(s => s.decision === "include")).toBe(true);
  });

  it("records exclude decisions when over budget", () => {
    const trace = tracePack(items, { maxTokens: 55 });
    const excluded = trace.steps.filter(s => s.decision === "exclude");
    expect(excluded.length).toBeGreaterThan(0);
  });

  it("records compress decisions", () => {
    const withCompression: ContextItem[] = [
      {
        id: "big",
        content: "Very long content",
        priority: 10,
        tokens: 100,
        compressions: [{ content: "Short", tokens: 20, note: "summary" }],
      },
    ];
    const trace = tracePack(
      withCompression,
      { maxTokens: 30 },
      { allowCompression: true }
    );
    const compressed = trace.steps.filter(s => s.decision === "compress");
    expect(compressed.length).toBe(1);
    expect(compressed[0].usedCompression).toBe(true);
    expect(compressed[0].compressedTokens).toBe(20);
  });

  it("includes createdAt timestamp", () => {
    const trace = tracePack(items, { maxTokens: 200 });
    expect(trace.createdAt).toBeDefined();
    expect(() => new Date(trace.createdAt)).not.toThrow();
  });

  it("trace pack matches pack result", () => {
    const trace = tracePack(items, { maxTokens: 90 });
    expect(trace.pack.selected.length).toBeGreaterThan(0);
    expect(trace.pack.totalTokens).toBeLessThanOrEqual(90);
  });

  it("produces stable snapshot", () => {
    const trace = tracePack(items, { maxTokens: 90 });
    const { createdAt, ...rest } = trace;
    expect(rest).toMatchSnapshot();
  });
});
