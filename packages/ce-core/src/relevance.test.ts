import { describe, it, expect } from "vitest";
import {
  extractKeywords,
  normalizeQuery,
  keywordRelevance,
  cosineSimilarity,
  embeddingRelevance,
  computeRelevance,
  enrichWithEmbeddings,
} from "./relevance.js";
import { createContextItem } from "./types.js";
import type { QueryContext, EmbeddingProvider } from "./types.js";

describe("extractKeywords", () => {
  it("filters stopwords and single chars, lowercases", () => {
    const result = extractKeywords("The Quick Brown Fox is a Great Animal");
    expect(result).toBeInstanceOf(Set);
    expect(result.has("the")).toBe(false);
    expect(result.has("is")).toBe(false);
    expect(result.has("a")).toBe(false);
    expect(result.has("quick")).toBe(true);
    expect(result.has("brown")).toBe(true);
    expect(result.has("fox")).toBe(true);
    expect(result.has("great")).toBe(true);
    expect(result.has("animal")).toBe(true);
  });

  it("returns empty set for empty string", () => {
    const result = extractKeywords("");
    expect(result.size).toBe(0);
  });
});

describe("normalizeQuery", () => {
  it("string input gets keywords auto-extracted", () => {
    const result = normalizeQuery("search for relevant documents");
    expect(result.text).toBe("search for relevant documents");
    expect(result.keywords).toBeInstanceOf(Array);
    expect(result.keywords!.length).toBeGreaterThan(0);
    expect(result.keywords).toContain("search");
    expect(result.keywords).toContain("relevant");
    expect(result.keywords).toContain("documents");
  });

  it("QueryContext input preserves existing keywords", () => {
    const input: QueryContext = {
      text: "hello world",
      keywords: ["custom", "keywords"],
    };
    const result = normalizeQuery(input);
    expect(result.keywords).toEqual(["custom", "keywords"]);
  });

  it("QueryContext without keywords gets them extracted", () => {
    const input: QueryContext = { text: "machine learning algorithms" };
    const result = normalizeQuery(input);
    expect(result.keywords).toBeInstanceOf(Array);
    expect(result.keywords!.length).toBeGreaterThan(0);
  });
});

describe("keywordRelevance", () => {
  it("returns 1.0 when all query keywords found", () => {
    const query: QueryContext = {
      text: "machine learning",
      keywords: ["machine", "learning"],
    };
    const item = createContextItem("doc", "machine learning is powerful");
    expect(keywordRelevance(query, item)).toBe(1.0);
  });

  it("returns 0.5 when half found", () => {
    const query: QueryContext = {
      text: "machine learning",
      keywords: ["machine", "learning"],
    };
    const item = createContextItem("doc", "machine is fast");
    expect(keywordRelevance(query, item)).toBe(0.5);
  });

  it("returns 0 when none found", () => {
    const query: QueryContext = {
      text: "machine learning",
      keywords: ["machine", "learning"],
    };
    const item = createContextItem("doc", "completely unrelated text");
    expect(keywordRelevance(query, item)).toBe(0);
  });

  it("returns 0 for empty query", () => {
    const query: QueryContext = {
      text: "",
      keywords: [],
    };
    const item = createContextItem("doc", "some content here");
    expect(keywordRelevance(query, item)).toBe(0);
  });
});

describe("cosineSimilarity", () => {
  it("identical vectors return 1.0", () => {
    const v = [1, 2, 3];
    expect(cosineSimilarity(v, v)).toBeCloseTo(1.0);
  });

  it("orthogonal vectors return 0.0", () => {
    expect(cosineSimilarity([1, 0], [0, 1])).toBeCloseTo(0.0);
  });

  it("mismatched lengths return 0", () => {
    expect(cosineSimilarity([1, 2], [1, 2, 3])).toBe(0);
  });

  it("zero vector returns 0", () => {
    expect(cosineSimilarity([0, 0, 0], [1, 2, 3])).toBe(0);
  });
});

describe("embeddingRelevance", () => {
  it("returns cosine similarity clamped to [0,1]", () => {
    const a = [1, 0, 0];
    const b = [1, 0, 0];
    expect(embeddingRelevance(a, b)).toBeCloseTo(1.0);
  });

  it("returns 0 if either embedding undefined", () => {
    expect(embeddingRelevance(undefined, [1, 2, 3])).toBe(0);
    expect(embeddingRelevance([1, 2, 3], undefined)).toBe(0);
    expect(embeddingRelevance(undefined, undefined)).toBe(0);
  });
});

describe("computeRelevance", () => {
  it("uses embedding when both available", () => {
    const query: QueryContext = {
      text: "test",
      keywords: ["test"],
      embedding: [1, 0, 0],
    };
    const item = createContextItem("doc", "unrelated words", {
      embedding: [1, 0, 0],
    });
    const score = computeRelevance(query, item);
    expect(score).toBeCloseTo(1.0);
  });

  it("falls back to keywords when no embeddings", () => {
    const query: QueryContext = {
      text: "machine learning",
      keywords: ["machine", "learning"],
    };
    const item = createContextItem("doc", "machine learning rocks");
    const score = computeRelevance(query, item);
    expect(score).toBe(1.0);
  });
});

describe("enrichWithEmbeddings", () => {
  it("calls provider.embed and enriches items and query", async () => {
    const mockProvider: EmbeddingProvider = {
      async embed(texts: string[]) {
        return texts.map((_, i) => [i * 0.1, 0.5, 0.3]);
      },
    };

    const items = [
      createContextItem("a", "first document"),
      createContextItem("b", "second document"),
    ];
    const query: QueryContext = { text: "search query" };

    const result = await enrichWithEmbeddings(items, query, mockProvider);
    expect(result.items).toHaveLength(2);
    expect(result.query.embedding).toBeDefined();
    expect(Array.isArray(result.query.embedding)).toBe(true);
    for (const item of result.items) {
      expect(item.embedding).toBeDefined();
      expect(Array.isArray(item.embedding)).toBe(true);
    }
  });
});
