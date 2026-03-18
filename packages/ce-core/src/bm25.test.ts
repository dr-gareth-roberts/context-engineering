import { describe, it, expect } from "vitest";
import { unicodeTokenize, createBM25Index } from "./bm25.js";

describe("unicodeTokenize", () => {
  it("tokenizes ASCII text into lowercase words", () => {
    expect(unicodeTokenize("Hello World")).toEqual(["hello", "world"]);
  });

  it("filters tokens with length <= 1", () => {
    expect(unicodeTokenize("I am a dog")).toEqual(["am", "dog"]);
  });

  it("handles Unicode characters", () => {
    const tokens = unicodeTokenize("café résumé naïve");
    expect(tokens).toContain("café");
    expect(tokens).toContain("résumé");
    expect(tokens).toContain("naïve");
  });

  it("handles CJK characters", () => {
    const tokens = unicodeTokenize("hello 世界");
    expect(tokens).toContain("hello");
    expect(tokens).toContain("世界");
    expect(tokens).toHaveLength(2);
  });

  it("returns empty array for empty string", () => {
    expect(unicodeTokenize("")).toEqual([]);
  });

  it("handles mixed alphanumeric", () => {
    const tokens = unicodeTokenize("node16 react19 ts5");
    expect(tokens).toContain("node16");
    expect(tokens).toContain("react19");
    expect(tokens).toContain("ts5");
  });

  it("returns empty array for null/undefined input", () => {
    expect(unicodeTokenize(null as any)).toEqual([]);
    expect(unicodeTokenize(undefined as any)).toEqual([]);
  });
});

describe("createBM25Index", () => {
  it("scores a matching document higher than non-matching", () => {
    const idx = createBM25Index();
    idx.add("doc1", "context engineering for language models");
    idx.add("doc2", "cooking recipes for pasta dishes");
    const s1 = idx.score("context engineering", "doc1");
    const s2 = idx.score("context engineering", "doc2");
    expect(s1).toBeGreaterThan(s2);
    expect(s2).toBe(0);
  });

  it("scoreAll returns scores for all documents", () => {
    const idx = createBM25Index();
    idx.add("a", "token budget packing");
    idx.add("b", "token estimation heuristic");
    idx.add("c", "unrelated content about weather");
    const scores = idx.scoreAll("token budget");
    expect(scores.get("a")).toBeGreaterThan(0);
    expect(scores.get("b")).toBeGreaterThan(0);
    expect(scores.get("c")).toBe(0);
    expect(scores.get("a")!).toBeGreaterThan(scores.get("b")!);
  });

  it("returns 0 for empty index", () => {
    const idx = createBM25Index();
    expect(idx.score("anything", "nonexistent")).toBe(0);
  });

  it("returns 0 for empty query", () => {
    const idx = createBM25Index();
    idx.add("doc1", "some content");
    expect(idx.score("", "doc1")).toBe(0);
  });

  it("tracks documentCount", () => {
    const idx = createBM25Index();
    expect(idx.documentCount).toBe(0);
    idx.add("a", "one");
    idx.add("b", "two");
    expect(idx.documentCount).toBe(2);
  });

  it("accepts custom k1 and b parameters", () => {
    const idx = createBM25Index({ k1: 2.0, b: 0.5 });
    idx.add("doc1", "test test test");
    const score = idx.score("test", "doc1");
    expect(score).toBeGreaterThan(0);
  });

  it("accepts custom tokenizer", () => {
    const idx = createBM25Index({
      tokenizer: text => text.split(",").map(s => s.trim().toLowerCase()),
    });
    idx.add("doc1", "alpha, beta, gamma");
    expect(idx.score("alpha", "doc1")).toBeGreaterThan(0);
  });

  it("IDF: rare terms score higher than common terms", () => {
    const idx = createBM25Index();
    idx.add("d1", "the common word appears here");
    idx.add("d2", "the common word too");
    idx.add("d3", "rare unique specialized term");
    const rareScore = idx.score("rare", "d3");
    const commonScore = idx.score("common", "d1");
    expect(rareScore).toBeGreaterThan(commonScore);
  });
});
