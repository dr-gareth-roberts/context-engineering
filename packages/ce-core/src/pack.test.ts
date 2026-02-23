import { describe, expect, it, vi } from "vitest";
import { pack } from "./pack.js";
import {
  ValidationError,
  BudgetExceededError,
  EstimationError,
} from "./errors.js";
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
    const itemsNoTokens: ContextItem[] = [
      { id: "x", content: "hello world" },
    ];
    const brokenEstimator: TokenEstimator = () => {
      throw new Error("estimator broken");
    };
    expect(() =>
      pack(itemsNoTokens, { maxTokens: 100 }, { tokenEstimator: brokenEstimator })
    ).toThrow(EstimationError);
  });

  it("uses custom summarizer that returns compressed content", () => {
    const bigItems: ContextItem[] = [
      { id: "big", content: "Very long content here", priority: 10, tokens: 200 },
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
