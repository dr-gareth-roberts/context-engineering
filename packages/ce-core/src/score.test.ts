import { describe, expect, it } from "vitest";
import { defaultItemScorer, createScorer } from "./score";
import type { ContextItem } from "./types";

const item: ContextItem = {
  id: "test",
  content: "Hello",
  priority: 10,
  recency: 5,
  metadata: { salience: 0.8 },
};

describe("defaultItemScorer", () => {
  it("computes default score: priority*1.0 + recency*0.7 + salience*0.5", () => {
    const score = defaultItemScorer(item);
    expect(score).toBeCloseTo(10 * 1.0 + 5 * 0.7 + 0.8 * 0.5);
  });

  it("returns explicit score when set", () => {
    const scored = { ...item, score: 42 };
    expect(defaultItemScorer(scored)).toBe(42);
  });

  it("handles missing optional fields", () => {
    const minimal: ContextItem = { id: "m", content: "test" };
    expect(defaultItemScorer(minimal)).toBe(0);
  });

  it("handles zero values", () => {
    const zero: ContextItem = {
      id: "z",
      content: "test",
      priority: 0,
      recency: 0,
      metadata: { salience: 0 },
    };
    expect(defaultItemScorer(zero)).toBe(0);
  });
});

describe("createScorer", () => {
  it("creates scorer with custom weights", () => {
    const scorer = createScorer({ priority: 2.0, recency: 0.0, salience: 1.0 });
    const score = scorer(item);
    expect(score).toBeCloseTo(10 * 2.0 + 5 * 0.0 + 0.8 * 1.0);
  });

  it("uses defaults for missing weight fields", () => {
    const scorer = createScorer({ priority: 2.0 });
    const score = scorer(item);
    expect(score).toBeCloseTo(10 * 2.0 + 5 * 0.7 + 0.8 * 0.5);
  });
});
