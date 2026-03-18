import { describe, expect, it, vi } from "vitest";
import { eliminateRedundancy, eliminateRedundancySync } from "./redundancy.js";
import { createContextItem } from "./types.js";
import type { ContextItem, EmbeddingProvider } from "./types.js";

class MessyProvider implements EmbeddingProvider {
  async embed(texts: string[]): Promise<number[][]> {
    return texts.map(text => {
      if (text === "zero") return [0, 0, 0];
      if (text === "identical-1") return [0.5, 0.5, 0.5];
      if (text === "identical-2") return [0.5, 0.5, 0.5];
      if (text === "opposite-1") return [1, -1, 1];
      if (text === "opposite-2") return [-1, 1, -1];
      // fallback unique vectors
      return [Math.random(), Math.random(), Math.random()];
    });
  }
}

describe("eliminateRedundancy - Edge Cases", () => {
  it("handles empty items array gracefully", async () => {
    const provider = new MessyProvider();
    const result = await eliminateRedundancy([], {
      embeddingProvider: provider,
    });
    expect(result).toEqual([]);
  });

  it("handles zero-magnitude vectors without NaN/Infinity issues", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "zero", recency: 1 },
      { id: "2", content: "zero", recency: 2 },
    ];
    // Cosine similarity with a zero vector should be 0.
    const result = await eliminateRedundancy(items, {
      embeddingProvider: provider,
      threshold: 0.5,
    });

    // Since similarity is 0 (below 0.5), they should NOT cluster, both survive
    expect(result.length).toBe(2);
  });

  it("handles perfectly identical vectors and resolves ties via priority", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "identical-1", recency: 5, priority: 10 },
      { id: "2", content: "identical-2", recency: 5, priority: 20 }, // Same recency, higher priority
      { id: "3", content: "identical-1", recency: 5, priority: 5 },
    ];
    const result = await eliminateRedundancy(items, {
      embeddingProvider: provider,
      threshold: 0.99,
    });

    // Should cluster into 1 group, keep the one with highest priority (id "2")
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("2");
  });

  it("handles opposite vectors (negative cosine similarity)", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "opposite-1", recency: 1 },
      { id: "2", content: "opposite-2", recency: 2 },
    ];
    // similarity should be -1.0
    const result = await eliminateRedundancy(items, {
      embeddingProvider: provider,
      threshold: 0.0,
    });

    // -1.0 is less than 0.0 threshold, so they should not cluster
    expect(result.length).toBe(2);
  });

  it("does not mutate original items array", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "identical-1", recency: 1 },
      { id: "2", content: "identical-2", recency: 2 },
    ];
    const originalLength = items.length;
    await eliminateRedundancy(items, { embeddingProvider: provider });
    expect(items.length).toBe(originalLength);
  });

  it("supports highest-priority strategy", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "identical-1", recency: 10, priority: 5 },
      { id: "2", content: "identical-2", recency: 50, priority: 20 },
    ];
    const result = await eliminateRedundancy(items, {
      embeddingProvider: provider,
      strategy: "highest-priority",
    });

    // Should keep the one with highest priority (id "2")
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("2");
  });
});

describe("eliminateRedundancySync (Jaccard)", () => {
  it("clusters items with high word overlap", () => {
    const items = [
      createContextItem("a", "the quick brown fox jumps over the lazy dog"),
      createContextItem("b", "the quick brown fox jumps over the lazy cat"),
      createContextItem(
        "c",
        "completely unrelated content about space rockets"
      ),
    ];
    const result = eliminateRedundancySync(items, {
      threshold: 0.7,
      strategy: "recent",
    });
    expect(result.length).toBe(2);
  });

  it("does not cluster items below threshold", () => {
    const items = [
      createContextItem("a", "alpha beta gamma delta epsilon"),
      createContextItem("b", "alpha beta gamma zeta omega"),
    ];
    // Jaccard = 3/7 ≈ 0.43, below default 0.8
    const result = eliminateRedundancySync(items);
    expect(result.length).toBe(2);
  });

  it("highest-priority strategy keeps highest priority", () => {
    const items = [
      {
        ...createContextItem("a", "same words repeated here again"),
        priority: 1,
      },
      {
        ...createContextItem("b", "same words repeated here again"),
        priority: 10,
      },
    ];
    const result = eliminateRedundancySync(items, {
      threshold: 0.8,
      strategy: "highest-priority",
    });
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("b");
  });

  it("recent strategy keeps most recent", () => {
    const items = [
      {
        ...createContextItem("a", "same words repeated here again"),
        recency: 1,
      },
      {
        ...createContextItem("b", "same words repeated here again"),
        recency: 10,
      },
    ];
    const result = eliminateRedundancySync(items, {
      threshold: 0.8,
      strategy: "recent",
    });
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("b");
  });

  it("returns empty array for empty input", () => {
    expect(eliminateRedundancySync([])).toEqual([]);
  });

  it("returns single item unchanged", () => {
    const items = [createContextItem("a", "only one item")];
    expect(eliminateRedundancySync(items)).toEqual(items);
  });

  it("uses 0.8 default threshold", () => {
    const items = [
      createContextItem("a", "alpha beta gamma delta epsilon zeta"),
      createContextItem("b", "alpha beta gamma delta epsilon omega"),
    ];
    // Jaccard = 5/7 ≈ 0.71, below 0.8 default
    const result = eliminateRedundancySync(items);
    expect(result.length).toBe(2);
  });
});
