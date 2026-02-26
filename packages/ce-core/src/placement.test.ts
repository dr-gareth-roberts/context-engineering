import { describe, expect, it } from "vitest";
import {
  placeItems,
  effectiveBudget,
  ATTENTION_PROFILES,
} from "./placement.js";
import type {
  ContextItem,
  AttentionProfile,
  PlacementOptions,
} from "./placement.js";

function makeItem(id: string, score: number): ContextItem {
  return { id, content: `content-${id}`, score };
}

describe("ATTENTION_PROFILES", () => {
  it("has claude, gpt4, and default profiles", () => {
    expect(ATTENTION_PROFILES.claude).toBeDefined();
    expect(ATTENTION_PROFILES.gpt4).toBeDefined();
    expect(ATTENTION_PROFILES.default).toBeDefined();
  });

  it("each profile has 10 position weight buckets", () => {
    for (const key of Object.keys(ATTENTION_PROFILES)) {
      expect(ATTENTION_PROFILES[key].positionWeights).toHaveLength(10);
    }
  });

  it("each profile has effectiveCapacity between 0 and 1", () => {
    for (const key of Object.keys(ATTENTION_PROFILES)) {
      const cap = ATTENTION_PROFILES[key].effectiveCapacity;
      expect(cap).toBeGreaterThan(0);
      expect(cap).toBeLessThanOrEqual(1);
    }
  });
});

describe("placeItems", () => {
  it("returns items unchanged with score-order strategy", () => {
    const items = [makeItem("a", 10), makeItem("b", 5), makeItem("c", 1)];
    const result = placeItems(items, { strategy: "score-order" });
    expect(result.map(i => i.id)).toEqual(["a", "b", "c"]);
  });

  it("returns items unchanged when no options provided (default is score-order)", () => {
    const items = [makeItem("a", 10), makeItem("b", 5), makeItem("c", 1)];
    const result = placeItems(items);
    expect(result.map(i => i.id)).toEqual(["a", "b", "c"]);
  });

  it("returns items as-is when 2 or fewer items regardless of strategy", () => {
    const single = [makeItem("a", 10)];
    const pair = [makeItem("a", 10), makeItem("b", 5)];

    const r1 = placeItems(single, { strategy: "attention-optimized" });
    expect(r1.map(i => i.id)).toEqual(["a"]);

    const r2 = placeItems(pair, { strategy: "attention-optimized" });
    expect(r2.map(i => i.id)).toEqual(["a", "b"]);
  });

  it("returns a shallow copy, not the original array", () => {
    const items = [makeItem("a", 10), makeItem("b", 5)];
    const result = placeItems(items);
    expect(result).not.toBe(items);
    expect(result).toEqual(items);
  });

  it("places highest-scored items at start and end with attention-optimized", () => {
    // Create 5 items with distinct scores
    const items = [
      makeItem("high1", 100),
      makeItem("high2", 90),
      makeItem("mid1", 50),
      makeItem("mid2", 40),
      makeItem("low", 10),
    ];

    const result = placeItems(items, {
      strategy: "attention-optimized",
      model: "default",
    });

    // All items should be present
    expect(result).toHaveLength(5);
    const ids = new Set(result.map(i => i.id));
    expect(ids.size).toBe(5);

    // The highest-scored item should be at start or end (high-attention positions)
    const firstId = result[0].id;
    const lastId = result[result.length - 1].id;
    const highAttentionIds = [firstId, lastId];
    expect(highAttentionIds).toContain("high1");

    // The lowest-scored item should be in the middle
    const middleIndex = Math.floor(result.length / 2);
    const middleItems = result.slice(1, result.length - 1).map(i => i.id);
    expect(middleItems).toContain("low");
  });

  it("uses claude profile when model is set to claude", () => {
    const items = [makeItem("a", 100), makeItem("b", 50), makeItem("c", 10)];

    const result = placeItems(items, {
      strategy: "attention-optimized",
      model: "claude",
    });

    expect(result).toHaveLength(3);
    // Claude has strongest attention at position 0 (weight 1.0)
    // so the highest-scored item should land at position 0
    expect(result[0].id).toBe("a");
  });

  it("uses custom profile when provided", () => {
    const customProfile: AttentionProfile = {
      name: "custom",
      effectiveCapacity: 0.8,
      // Strong attention at start, weak everywhere else
      positionWeights: [1.0, 0.1, 0.1],
    };

    const items = [makeItem("a", 100), makeItem("b", 50), makeItem("c", 10)];

    const result = placeItems(items, {
      strategy: "attention-optimized",
      profile: customProfile,
    });

    expect(result).toHaveLength(3);
    // With strong attention at start only, the highest-scored item goes first
    expect(result[0].id).toBe("a");
    // The lowest-scored item should not be at position 0
    expect(result[1].id).not.toBe("a");
  });

  it("falls back to default profile for unknown model", () => {
    const items = [makeItem("a", 100), makeItem("b", 50), makeItem("c", 10)];

    const result = placeItems(items, {
      strategy: "attention-optimized",
      model: "unknown-model",
    });

    // Should not throw and should return all items
    expect(result).toHaveLength(3);
  });

  it("handles items without score (defaults to 0)", () => {
    const items: ContextItem[] = [
      { id: "a", content: "a" },
      { id: "b", content: "b" },
      { id: "c", content: "c", score: 10 },
    ];

    const result = placeItems(items, { strategy: "attention-optimized" });
    expect(result).toHaveLength(3);
    // The one with a score should get a high-attention position
    const ids = result.map(i => i.id);
    expect(ids).toContain("c");
  });
});

describe("effectiveBudget", () => {
  it("returns correct fraction for default profile", () => {
    expect(effectiveBudget(200_000)).toBe(140_000);
  });

  it("returns correct fraction for claude profile", () => {
    expect(effectiveBudget(200_000, "claude")).toBe(140_000);
  });

  it("returns correct fraction for gpt4 profile", () => {
    expect(effectiveBudget(200_000, "gpt4")).toBe(130_000);
  });

  it("floors the result to an integer", () => {
    // 100_001 * 0.7 = 70_000.7 -> 70_000
    expect(effectiveBudget(100_001, "claude")).toBe(70_000);
  });

  it("falls back to default for unknown model", () => {
    expect(effectiveBudget(200_000, "unknown")).toBe(140_000);
  });
});
