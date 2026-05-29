import { describe, expect, it, vi } from "vitest";
import { pack, packAsync } from "./pack.js";
import {
  ValidationError,
  BudgetExceededError,
  EstimationError,
} from "./errors.js";
import { createContextItem } from "./types.js";
import type { ContextItem, Summarizer, TokenEstimator } from "./types.js";
import type { Logger } from "./logger.js";

const items: ContextItem[] = [
  { id: "a", content: "High priority", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 },
];

describe("pack", () => {
  it("selects highest scored items within budget", () => {
    const packResult = pack(items, { maxTokens: 90 });
    const selectedIds = packResult.selected.map(item => item.id);
    expect(selectedIds).toContain("a");
    expect(selectedIds).toContain("c");
    expect(selectedIds).not.toContain("b");
  });

  it("uses compression when allowed", () => {
    const compressedItems: ContextItem[] = [
      {
        id: "a",
        content: "Long content",
        priority: 10,
        tokens: 100,
        compressions: [{ content: "Short", tokens: 30, note: "summary" }],
      },
    ];
    const packResult = pack(
      compressedItems,
      { maxTokens: 40 },
      { allowCompression: true }
    );
    expect(packResult.selected[0].content).toBe("Short");
  });

  it("returns empty pack for empty items array", () => {
    const result = pack([], { maxTokens: 100 });
    expect(result.selected).toEqual([]);
    expect(result.dropped).toEqual([]);
    expect(result.totalTokens).toBe(0);
  });

  it("throws ValidationError for invalid budget", () => {
    expect(() => pack(items, { maxTokens: -100 })).toThrow(ValidationError);
  });

  it("throws ValidationError for zero budget", () => {
    expect(() => pack(items, { maxTokens: 0 })).toThrow(ValidationError);
  });

  it("throws ValidationError for item missing id", () => {
    const bad = [{ content: "no id" }] as ContextItem[];
    expect(() => pack(bad, { maxTokens: 100 })).toThrow(ValidationError);
  });

  it("throws BudgetExceededError when reserveTokens >= maxTokens", () => {
    expect(() => pack(items, { maxTokens: 100, reserveTokens: 100 })).toThrow(
      BudgetExceededError
    );
  });

  it("drops all items when none fit budget", () => {
    const result = pack(items, { maxTokens: 1 });
    expect(result.selected).toEqual([]);
    expect(result.dropped.length).toBe(3);
  });

  it("uses custom scorer via weights option", () => {
    const result = pack(
      items,
      { maxTokens: 90 },
      { weights: { priority: 0, recency: 1.0 } }
    );
    expect(result.selected.length).toBeGreaterThan(0);
  });

  it("produces stable snapshot output", () => {
    const result = pack(items, { maxTokens: 90 });
    expect(result).toMatchSnapshot();
  });

  it("throws EstimationError when token estimator throws", () => {
    const itemsNoTokens: ContextItem[] = [{ id: "x", content: "hello world" }];
    const brokenEstimator: TokenEstimator = () => {
      throw new Error("estimator broken");
    };
    expect(() =>
      pack(
        itemsNoTokens,
        { maxTokens: 100 },
        { tokenEstimator: brokenEstimator }
      )
    ).toThrow(EstimationError);
  });

  it("uses custom summarizer that returns compressed content", () => {
    const bigItems: ContextItem[] = [
      {
        id: "big",
        content: "Very long content here",
        priority: 10,
        tokens: 200,
      },
    ];
    const summarizer: Summarizer = (_item, _targetTokens) => ({
      id: "big",
      content: "compressed",
      tokens: 20,
    });
    const result = pack(
      bigItems,
      { maxTokens: 50 },
      { allowCompression: true, summarizer }
    );
    expect(result.selected.length).toBe(1);
    expect(result.selected[0].content).toBe("compressed");
    expect(result.selected[0].tokens).toBe(20);
  });

  it("calls logger.info during packing", () => {
    const mockLogger: Logger = {
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    };
    pack(items, { maxTokens: 200 }, { logger: mockLogger });
    expect(mockLogger.info).toHaveBeenCalled();
  });
});

describe("pack edge cases", () => {
  it("selects item with tokens=0 without re-estimating", () => {
    const zeroTokenItem: ContextItem[] = [
      { id: "zero", content: "I have zero tokens", priority: 5, tokens: 0 },
    ];
    const result = pack(zeroTokenItem, { maxTokens: 10 });
    expect(result.selected.length).toBe(1);
    expect(result.selected[0].id).toBe("zero");
    expect(result.selected[0].tokens).toBe(0);
    expect(result.totalTokens).toBe(0);
  });

  it("throws ValidationError for item with negative tokens", () => {
    const negativeTokenItem: ContextItem[] = [
      { id: "neg", content: "Negative tokens", tokens: -5 },
    ];
    expect(() => pack(negativeTokenItem, { maxTokens: 100 })).toThrow(
      ValidationError
    );
  });

  it("packs items with all-undefined scoring fields", () => {
    const bareItems: ContextItem[] = [
      { id: "bare1", content: "Just content, no scores" },
      { id: "bare2", content: "Another bare item" },
    ];
    const result = pack(bareItems, { maxTokens: 1000 });
    expect(result.selected.length).toBe(2);
    const ids = result.selected.map(i => i.id);
    expect(ids).toContain("bare1");
    expect(ids).toContain("bare2");
  });

  it("selects item that exactly fills budget=1", () => {
    const tinyItem: ContextItem[] = [
      { id: "tiny", content: "x", priority: 1, tokens: 1 },
    ];
    const result = pack(tinyItem, { maxTokens: 1 });
    expect(result.selected.length).toBe(1);
    expect(result.selected[0].id).toBe("tiny");
    expect(result.totalTokens).toBe(1);
  });

  it("processes items with duplicate IDs without crashing", () => {
    const dupeItems: ContextItem[] = [
      { id: "dupe", content: "First", priority: 5, tokens: 10 },
      { id: "dupe", content: "Second", priority: 3, tokens: 10 },
    ];
    const result = pack(dupeItems, { maxTokens: 100 });
    expect(result.selected.length).toBe(2);
    expect(result.totalTokens).toBe(20);
  });
});

describe("createContextItem", () => {
  it("creates a valid item with only id and content", () => {
    const item = createContextItem("x", "hello");
    expect(item.id).toBe("x");
    expect(item.content).toBe("hello");
    expect(item.priority).toBeUndefined();
    expect(item.kind).toBeUndefined();
    expect(item.tokens).toBeUndefined();
  });

  it("creates an item with overrides", () => {
    const item = createContextItem("x", "hello", {
      priority: 10,
      kind: "code",
    });
    expect(item.id).toBe("x");
    expect(item.content).toBe("hello");
    expect(item.priority).toBe(10);
    expect(item.kind).toBe("code");
  });
});

describe("NaN/Infinity validation", () => {
  it("rejects Infinity in priority", () => {
    const items: ContextItem[] = [
      { id: "a", content: "test", priority: Infinity },
    ];
    expect(() => pack(items, { maxTokens: 100 })).toThrow(ValidationError);
  });

  it("rejects NaN in priority", () => {
    const items: ContextItem[] = [{ id: "a", content: "test", priority: NaN }];
    expect(() => pack(items, { maxTokens: 100 })).toThrow(ValidationError);
  });

  it("rejects Infinity in tokens", () => {
    const items: ContextItem[] = [
      { id: "a", content: "test", tokens: Infinity },
    ];
    expect(() => pack(items, { maxTokens: 100 })).toThrow(ValidationError);
  });

  it("rejects NaN in budget maxTokens", () => {
    expect(() => pack([], { maxTokens: NaN })).toThrow(ValidationError);
  });
});

describe("pack with query", () => {
  it("with no query produces identical output to default", () => {
    const items = [
      createContextItem("a", "alpha content", { priority: 5 }),
      createContextItem("b", "beta content", { priority: 3 }),
    ];
    const budget = { maxTokens: 1000 };

    const withoutQuery = pack(items, budget);
    const withQuery = pack(items, budget, {});

    expect(withoutQuery.selected.map(i => i.id)).toEqual(
      withQuery.selected.map(i => i.id)
    );
  });

  it("with query reorders items by relevance", () => {
    const items = [
      createContextItem("irrelevant", "unrelated xyz content", { priority: 5 }),
      createContextItem("relevant", "machine learning algorithms", {
        priority: 5,
      }),
    ];
    const budget = { maxTokens: 100 };

    const result = pack(items, budget, { query: "machine learning" });

    // The relevant item should be selected first (higher score)
    expect(result.selected[0].id).toBe("relevant");
  });

  it("packAsync calls embedding provider when present", async () => {
    const embedCalls: string[][] = [];
    const mockProvider = {
      async embed(texts: string[]) {
        embedCalls.push(texts);
        return texts.map(() => [0.5, 0.5, 0.5]);
      },
    };

    const items = [
      createContextItem("a", "alpha", { priority: 5 }),
      createContextItem("b", "beta", { priority: 3 }),
    ];

    await packAsync(
      items,
      { maxTokens: 1000 },
      {
        query: "test query",
        embeddingProvider: mockProvider,
      }
    );

    expect(embedCalls.length).toBe(1);
    // Should have embedded 2 items + 1 query = 3 texts
    expect(embedCalls[0]).toHaveLength(3);
  });

  it("throws ValidationError (not TypeError) for non-string content on the redundancyConfig path", () => {
    // Regression: redundancy elimination tokenizes item.content before input
    // validation ran, so non-string content threw a raw
    // "text.toLowerCase is not a function" TypeError instead of the documented
    // ValidationError. Validation must now run first.
    const badItems = [
      { id: "x", content: 123 as unknown as string, tokens: 10 },
    ];
    expect(() =>
      pack(
        badItems,
        { maxTokens: 100 },
        { redundancyConfig: { threshold: 0.8 } }
      )
    ).toThrow(ValidationError);
  });

  it("packAsync throws ValidationError (not TypeError) for non-string content on the redundancyConfig path", async () => {
    const badItems = [
      { id: "x", content: 123 as unknown as string, tokens: 10 },
    ];
    await expect(
      packAsync(
        badItems,
        { maxTokens: 100 },
        { redundancyConfig: { threshold: 0.8 } }
      )
    ).rejects.toThrow(ValidationError);
  });
});
