import { describe, expect, it } from "vitest";
import { analyzeContext, analyzeContextPack } from "./quality.js";
import type { ContextItem, ContextPack } from "./types.js";

const makeItem = (
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem => ({
  id,
  content,
  ...overrides,
});

describe("analyzeContext", () => {
  it("returns all zeros for empty items", () => {
    const result = analyzeContext([]);
    expect(result).toEqual({
      itemCount: 0,
      totalTokens: 0,
      density: 0,
      diversity: 0,
      freshness: 0,
      redundancy: 0,
      overall: 0,
    });
  });

  it("returns reasonable metrics for a single item", () => {
    const items = [makeItem("a", "The quick brown fox jumps over the lazy dog")];
    const result = analyzeContext(items);

    expect(result.itemCount).toBe(1);
    expect(result.totalTokens).toBeGreaterThan(0);
    expect(result.density).toBeGreaterThan(0);
    expect(result.density).toBeLessThanOrEqual(1);
    expect(result.diversity).toBeGreaterThan(0);
    expect(result.diversity).toBeLessThanOrEqual(1);
    // Single item with no recency => freshness 0
    expect(result.freshness).toBe(0);
    // Single item => no pairs => redundancy 0
    expect(result.redundancy).toBe(0);
    expect(result.overall).toBeGreaterThan(0);
    expect(result.overall).toBeLessThanOrEqual(1);
  });

  it("scores high diversity items higher than repeated items", () => {
    const diverse = [
      makeItem("a", "Machine learning algorithms optimize neural networks"),
      makeItem("b", "Quantum computing leverages superposition entanglement"),
      makeItem("c", "Distributed databases ensure consistency availability"),
    ];
    const repeated = [
      makeItem("a", "The cat sat on the mat in the room"),
      makeItem("b", "The cat sat on the mat in the house"),
      makeItem("c", "The cat sat on the mat in the garden"),
    ];

    const diverseResult = analyzeContext(diverse);
    const repeatedResult = analyzeContext(repeated);

    expect(diverseResult.diversity).toBeGreaterThan(repeatedResult.diversity);
  });

  it("reports high redundancy for duplicate content", () => {
    const duplicates = [
      makeItem("a", "The quick brown fox jumps over the lazy dog"),
      makeItem("b", "The quick brown fox jumps over the lazy dog"),
      makeItem("c", "The quick brown fox jumps over the lazy dog"),
    ];
    const unique = [
      makeItem("a", "Machine learning algorithms optimize neural networks"),
      makeItem("b", "Quantum computing leverages superposition entanglement"),
      makeItem("c", "Distributed databases ensure consistency availability"),
    ];

    const dupResult = analyzeContext(duplicates);
    const uniqueResult = analyzeContext(unique);

    expect(dupResult.redundancy).toBeGreaterThan(0.5);
    expect(uniqueResult.redundancy).toBeLessThan(dupResult.redundancy);
  });

  it("reflects recency values in freshness", () => {
    const fresh = [
      makeItem("a", "Recent content one", { recency: 8 }),
      makeItem("b", "Recent content two", { recency: 9 }),
      makeItem("c", "Recent content three", { recency: 7 }),
    ];
    const stale = [
      makeItem("a", "Stale content one", { recency: 1 }),
      makeItem("b", "Stale content two", { recency: 2 }),
      makeItem("c", "Stale content three", { recency: 3 }),
    ];

    const freshResult = analyzeContext(fresh);
    const staleResult = analyzeContext(stale);

    expect(freshResult.freshness).toBe(1);
    expect(staleResult.freshness).toBe(0);
  });

  it("keeps overall score between 0 and 1", () => {
    const items = [
      makeItem("a", "Alpha bravo charlie delta echo foxtrot", {
        recency: 10,
      }),
      makeItem("b", "Golf hotel india juliet kilo lima", { recency: 8 }),
      makeItem("c", "Mike november oscar papa quebec romeo", { recency: 6 }),
    ];
    const result = analyzeContext(items);

    expect(result.overall).toBeGreaterThanOrEqual(0);
    expect(result.overall).toBeLessThanOrEqual(1);
  });

  it("uses pre-computed tokens when available", () => {
    const items = [makeItem("a", "Hello world", { tokens: 100 })];
    const result = analyzeContext(items);
    expect(result.totalTokens).toBe(100);
  });
});

describe("analyzeContextPack", () => {
  it("delegates to analyzeContext with pack.selected", () => {
    const items: ContextItem[] = [
      makeItem("a", "First item content here"),
      makeItem("b", "Second item content here"),
    ];
    const pack: ContextPack = {
      budget: { maxTokens: 1000 },
      selected: items,
      dropped: [],
      totalTokens: 50,
    };

    const packResult = analyzeContextPack(pack);
    const directResult = analyzeContext(items);

    expect(packResult).toEqual(directResult);
  });
});
