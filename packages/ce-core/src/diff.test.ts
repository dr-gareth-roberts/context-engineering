import { describe, expect, it } from "vitest";
import { diff } from "./diff";
import type { ContextItem, ContextPack } from "./types";

const before: ContextItem[] = [
  { id: "a", content: "Alpha", tokens: 10 },
  { id: "b", content: "Beta", tokens: 20 },
];

const after: ContextItem[] = [
  { id: "a", content: "Alpha", tokens: 10 },
  { id: "c", content: "Gamma", tokens: 15 },
];

describe("diff", () => {
  it("detects added and removed items", () => {
    const result = diff(before, after);
    expect(result.added.map(i => i.id)).toEqual(["c"]);
    expect(result.removed.map(i => i.id)).toEqual(["b"]);
    expect(result.kept.map(i => i.id)).toEqual(["a"]);
  });

  it("detects content changes", () => {
    const changed: ContextItem[] = [
      { id: "a", content: "Alpha modified", tokens: 10 },
    ];
    const result = diff(before, changed);
    expect(result.changed.length).toBe(1);
    expect(result.changed[0].before.content).toBe("Alpha");
    expect(result.changed[0].after.content).toBe("Alpha modified");
  });

  it("detects token changes", () => {
    const changed: ContextItem[] = [{ id: "a", content: "Alpha", tokens: 999 }];
    const result = diff(before, changed);
    expect(result.changed.length).toBe(1);
  });

  it("handles empty before", () => {
    const result = diff([], after);
    expect(result.added.length).toBe(2);
    expect(result.removed.length).toBe(0);
  });

  it("handles empty after", () => {
    const result = diff(before, []);
    expect(result.removed.length).toBe(2);
    expect(result.added.length).toBe(0);
  });

  it("handles both empty", () => {
    const result = diff([], []);
    expect(result.added).toEqual([]);
    expect(result.removed).toEqual([]);
    expect(result.kept).toEqual([]);
    expect(result.changed).toEqual([]);
  });

  it("handles identical arrays", () => {
    const result = diff(before, [...before]);
    expect(result.kept.length).toBe(2);
    expect(result.added).toEqual([]);
    expect(result.removed).toEqual([]);
    expect(result.changed).toEqual([]);
  });

  it("accepts ContextPack inputs", () => {
    const beforePack: ContextPack = {
      budget: { maxTokens: 100 },
      selected: before,
      dropped: [],
      totalTokens: 30,
    };
    const afterPack: ContextPack = {
      budget: { maxTokens: 100 },
      selected: after,
      dropped: [],
      totalTokens: 25,
    };
    const result = diff(beforePack, afterPack);
    expect(result.added.map(i => i.id)).toEqual(["c"]);
    expect(result.removed.map(i => i.id)).toEqual(["b"]);
  });

  it("produces stable snapshot", () => {
    const result = diff(before, after);
    expect(result).toMatchSnapshot();
  });
});
