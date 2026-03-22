import { describe, it, expect } from "vitest";
import {
  computeInformationGain,
  computeInformationGainAsync,
} from "../information-gain.js";
import type { ContextItem, EmbeddingProvider } from "@context-engineering/core";

function makeItem(
  id: string,
  content: string,
  embedding?: number[]
): ContextItem {
  return { id, content, ...(embedding ? { embedding } : {}) };
}

describe("computeInformationGain", () => {
  it("returns gain=1.0 for novel candidate with no overlap", () => {
    const candidate = makeItem(
      "new",
      "quantum computing advances in superconducting qubits"
    );
    const existing = [
      makeItem(
        "old",
        "traditional database indexing strategies for relational systems"
      ),
    ];

    const result = computeInformationGain(candidate, existing);

    // Completely different content should yield high novelty
    expect(result.novelty).toBeGreaterThan(0.8);
    expect(result.gain).toBeGreaterThan(0.5);
  });

  it("returns gain near 0 for duplicate of existing item", () => {
    const content = "the quick brown fox jumps over the lazy dog";
    const candidate = makeItem("dup", content);
    const existing = [makeItem("orig", content)];

    const result = computeInformationGain(candidate, existing);

    // Identical content = Jaccard similarity of 1.0, novelty = 0
    expect(result.novelty).toBe(0);
    expect(result.gain).toBeLessThan(0.25);
  });

  it("gain decreases proportionally with increasing Jaccard similarity", () => {
    const candidate = makeItem("c", "alpha beta gamma delta epsilon");
    const lowOverlap = [makeItem("lo", "zeta eta theta iota kappa")];
    const highOverlap = [makeItem("hi", "alpha beta gamma delta zeta")];

    const lowResult = computeInformationGain(candidate, lowOverlap);
    const highResult = computeInformationGain(candidate, highOverlap);

    expect(lowResult.novelty).toBeGreaterThan(highResult.novelty);
    expect(lowResult.gain).toBeGreaterThan(highResult.gain);
  });

  it("uses embedding cosine similarity when embeddings are provided", () => {
    // Identical embeddings = cosine similarity 1.0
    const embedding = [1, 0, 0];
    const candidate = makeItem("c", "content a", embedding);
    const existing = [makeItem("e", "content b", embedding)];

    const result = computeInformationGain(candidate, existing);

    expect(result.novelty).toBe(0);
    expect(result.gain).toBeLessThan(0.25);
  });

  it("query relevance influences final gain score", () => {
    const candidate = makeItem("c", "machine learning neural network training");
    const existing: ContextItem[] = [];

    const withQuery = computeInformationGain(candidate, existing, {
      queryContext: "machine learning neural network",
    });

    const withoutQuery = computeInformationGain(candidate, existing);

    // With a relevant query, relevance should be higher than neutral 0.5
    expect(withQuery.queryRelevance).toBeGreaterThan(
      withoutQuery.queryRelevance
    );
    expect(withQuery.gain).toBeGreaterThan(withoutQuery.gain);
  });

  it("returns novelty=1.0 when existing context is empty", () => {
    const candidate = makeItem("c", "any content here");
    const result = computeInformationGain(candidate, []);

    expect(result.novelty).toBe(1.0);
  });

  it("custom noveltyWeight and relevanceWeight work correctly", () => {
    const candidate = makeItem("c", "some unique content");
    const existing: ContextItem[] = [];

    const noveltyHeavy = computeInformationGain(candidate, existing, {
      noveltyWeight: 0.9,
      relevanceWeight: 0.1,
    });

    const relevanceHeavy = computeInformationGain(candidate, existing, {
      noveltyWeight: 0.1,
      relevanceWeight: 0.9,
    });

    // novelty=1.0 for both, but different weights on neutral relevance (0.5)
    // noveltyHeavy: 1.0*0.9 + 0.5*0.1 = 0.95
    // relevanceHeavy: 1.0*0.1 + 0.5*0.9 = 0.55
    expect(noveltyHeavy.gain).toBeGreaterThan(relevanceHeavy.gain);
    expect(noveltyHeavy.gain).toBeCloseTo(0.95, 1);
    expect(relevanceHeavy.gain).toBeCloseTo(0.55, 1);
  });
});

describe("computeInformationGainAsync", () => {
  it("computes embeddings on the fly when provider is given", async () => {
    const mockProvider: EmbeddingProvider = {
      async embed(texts: string[]): Promise<number[][]> {
        // Return orthogonal embeddings for different texts
        return texts.map((_, i) => {
          const vec = [0, 0, 0];
          vec[i % 3] = 1;
          return vec;
        });
      },
    };

    const candidate = makeItem("c", "novel content");
    const existing = [makeItem("e", "existing content")];

    const result = await computeInformationGainAsync(candidate, existing, {
      embeddingProvider: mockProvider,
    });

    // Orthogonal embeddings = cosine 0, novelty = 1.0
    expect(result.novelty).toBe(1.0);
  });

  it("falls back to sync computation without provider", async () => {
    const content = "identical text identical text";
    const candidate = makeItem("c", content);
    const existing = [makeItem("e", content)];

    const result = await computeInformationGainAsync(candidate, existing);

    expect(result.novelty).toBe(0);
  });
});
