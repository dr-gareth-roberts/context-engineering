import { describe, expect, it } from "vitest";
import { estimateCost, projectCosts, MODEL_PRICING } from "./cost.js";
import type { CacheAwarePack } from "./cache-topology.js";
import type { Budget } from "./types.js";

function makeCacheAwarePack(
  totalTokens: number,
  cacheableTokens: number
): CacheAwarePack {
  const budget: Budget = { maxTokens: totalTokens + 1000 };
  return {
    budget,
    selected: [],
    dropped: [],
    totalTokens,
    stats: {},
    cacheKey: "test",
    cacheableTokens,
    volatileTokens: totalTokens - cacheableTokens,
    cacheEfficiency: totalTokens > 0 ? cacheableTokens / totalTokens : 0,
    partitionBoundaries: [0, 0],
  };
}

describe("estimateCost", () => {
  it("computes cost for claude-sonnet-4-6", () => {
    // 4000 total tokens: 3000 cached, 1000 volatile
    const pack = makeCacheAwarePack(4000, 3000);
    const cost = estimateCost(pack, "claude-sonnet-4-6", 500);

    expect(cost.model).toBe("claude-sonnet-4-6");
    expect(cost.inputTokens).toBe(4000);
    expect(cost.cachedTokens).toBe(3000);
    expect(cost.uncachedTokens).toBe(1000);
    expect(cost.outputTokens).toBe(500);

    // Without cache: (4000/1M)*3 + (500/1M)*15 = 0.012 + 0.0075 = 0.0195
    expect(cost.costWithoutCache).toBeCloseTo(0.0195, 4);

    // With cache: (3000/1M)*0.3 + (1000/1M)*3 + (500/1M)*15
    //           = 0.0009 + 0.003 + 0.0075 = 0.0114
    expect(cost.costWithCache).toBeCloseTo(0.0114, 4);

    expect(cost.savings).toBeGreaterThan(0);
    expect(cost.savingsPercent).toBeGreaterThan(0);
  });

  it("computes cost for claude-opus-4-6", () => {
    const pack = makeCacheAwarePack(8000, 6000);
    const cost = estimateCost(pack, "claude-opus-4-6", 1000);

    // Without: (8000/1M)*15 + (1000/1M)*75 = 0.12 + 0.075 = 0.195
    expect(cost.costWithoutCache).toBeCloseTo(0.195, 4);

    // With: (6000/1M)*1.5 + (2000/1M)*15 + (1000/1M)*75
    //     = 0.009 + 0.03 + 0.075 = 0.114
    expect(cost.costWithCache).toBeCloseTo(0.114, 4);

    expect(cost.savings).toBeCloseTo(0.081, 3);
    expect(cost.savingsPercent).toBeGreaterThan(40);
  });

  it("shows zero savings when nothing is cached", () => {
    const pack = makeCacheAwarePack(4000, 0);
    const cost = estimateCost(pack, "claude-sonnet-4-6");

    expect(cost.savings).toBe(0);
    expect(cost.savingsPercent).toBe(0);
    expect(cost.cacheEfficiency).toBe(0);
  });

  it("shows max savings when everything is cached", () => {
    const pack = makeCacheAwarePack(4000, 4000);
    const cost = estimateCost(pack, "claude-sonnet-4-6");

    expect(cost.savings).toBeGreaterThan(0);
    expect(cost.cacheEfficiency).toBe(1);
  });

  it("accepts custom pricing", () => {
    const pack = makeCacheAwarePack(1000, 500);
    const cost = estimateCost(pack, "custom-model", 100, {
      inputPerMillion: 10,
      cachedInputPerMillion: 1,
      outputPerMillion: 30,
    });

    expect(cost.model).toBe("custom-model");
    expect(cost.costWithoutCache).toBeGreaterThan(0);
    expect(cost.savings).toBeGreaterThan(0);
  });

  it("throws for unknown model without custom pricing", () => {
    const pack = makeCacheAwarePack(1000, 500);
    expect(() => estimateCost(pack, "unknown-model")).toThrow("Unknown model");
  });

  it("throws for prototype-member model names instead of producing NaN", () => {
    // Regression: MODEL_PRICING is a plain object, so an own-property check is
    // required. Names like "toString"/"constructor"/"hasOwnProperty"/"valueOf"
    // resolve to inherited Object.prototype members, which previously bypassed
    // the "Unknown model" guard and yielded NaN cost fields.
    const pack = makeCacheAwarePack(1000, 500);
    for (const name of [
      "toString",
      "constructor",
      "valueOf",
      "hasOwnProperty",
      "__proto__",
    ]) {
      expect(() => estimateCost(pack, name)).toThrow("Unknown model");
    }
  });

  it("has pricing for common models", () => {
    expect(MODEL_PRICING["claude-opus-4-6"]).toBeDefined();
    expect(MODEL_PRICING["claude-sonnet-4-6"]).toBeDefined();
    expect(MODEL_PRICING["gpt-4.1"]).toBeDefined();
    expect(MODEL_PRICING["gpt-4o"]).toBeDefined();
    expect(MODEL_PRICING["o3"]).toBeDefined();
  });
});

describe("projectCosts", () => {
  it("projects costs over multiple requests", () => {
    const pack = makeCacheAwarePack(4000, 3000);
    const projection = projectCosts(pack, "claude-sonnet-4-6", 1000);

    expect(projection.requestCount).toBe(1000);
    expect(projection.totalWithoutCache).toBeGreaterThan(0);
    expect(projection.totalWithCache).toBeGreaterThan(0);
    expect(projection.totalSavings).toBeGreaterThan(0);
    expect(projection.totalWithCache).toBeLessThan(
      projection.totalWithoutCache
    );
  });

  it("includes monthly estimate when requestsPerDay provided", () => {
    const pack = makeCacheAwarePack(4000, 3000);
    const projection = projectCosts(pack, "claude-sonnet-4-6", 1000, {
      requestsPerDay: 500,
    });

    expect(projection.monthlyEstimate).toBeDefined();
    expect(projection.monthlyEstimate!.requestsPerDay).toBe(500);
    expect(projection.monthlyEstimate!.monthlySavings).toBeGreaterThan(0);
  });

  it("handles zero cache", () => {
    const pack = makeCacheAwarePack(4000, 0);
    const projection = projectCosts(pack, "claude-sonnet-4-6", 100);

    expect(projection.totalSavings).toBe(0);
  });

  it("concrete savings example: 8k context, 75% cached, Opus", () => {
    const pack = makeCacheAwarePack(8000, 6000);
    const projection = projectCosts(pack, "claude-opus-4-6", 10000, {
      outputTokens: 1000,
      requestsPerDay: 1000,
    });

    // At 10k requests with Opus: should save hundreds of dollars
    expect(projection.totalSavings).toBeGreaterThan(500);
    expect(projection.monthlyEstimate!.monthlySavings).toBeGreaterThan(1000);
  });
});
