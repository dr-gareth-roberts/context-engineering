import { describe, it, expect } from "vitest";
import type { ContextItem, Budget } from "@context-engineering/core";
import {
  computeStats,
  extractFingerprint,
  compareFingerprints,
} from "../fingerprint.js";
import type { Fingerprint } from "../types.js";

function makeItem(
  overrides: Partial<ContextItem> & { id: string; content: string }
): ContextItem {
  return {
    id: overrides.id,
    content: overrides.content,
    kind: overrides.kind,
    priority: overrides.priority,
    recency: overrides.recency,
    tokens: overrides.tokens,
    ...overrides,
  } as ContextItem;
}

describe("computeStats", () => {
  it("returns zeroed stats for empty array", () => {
    const stats = computeStats([]);
    expect(stats).toEqual({ min: 0, max: 0, mean: 0, std: 0 });
  });

  it("handles single value", () => {
    const stats = computeStats([5]);
    expect(stats.min).toBe(5);
    expect(stats.max).toBe(5);
    expect(stats.mean).toBe(5);
    expect(stats.std).toBe(0);
  });

  it("handles identical values", () => {
    const stats = computeStats([3, 3, 3]);
    expect(stats.min).toBe(3);
    expect(stats.max).toBe(3);
    expect(stats.mean).toBe(3);
    expect(stats.std).toBe(0);
  });

  it("computes correct stats for varied values", () => {
    const stats = computeStats([2, 4, 4, 4, 5, 5, 7, 9]);
    expect(stats.min).toBe(2);
    expect(stats.max).toBe(9);
    expect(stats.mean).toBe(5);
    expect(stats.std).toBeCloseTo(2, 0);
  });

  it("handles negative values", () => {
    const stats = computeStats([-1, 0, 1]);
    expect(stats.min).toBe(-1);
    expect(stats.max).toBe(1);
    expect(stats.mean).toBe(0);
  });
});

describe("extractFingerprint", () => {
  it("returns empty fingerprint for empty items", () => {
    const fp = extractFingerprint([]);
    expect(fp.kindsPresent).toEqual([]);
    expect(fp.kindRatios).toEqual({});
    expect(fp.itemCount).toBe(0);
    expect(fp.stalenessRatio).toBe(0);
    expect(fp.redundancyEstimate).toBe(0);
    expect(fp.tokenUtilization).toBe(0);
  });

  it("extracts kinds correctly", () => {
    const items = [
      makeItem({ id: "1", content: "hello", kind: "system" }),
      makeItem({ id: "2", content: "world", kind: "retrieval" }),
      makeItem({ id: "3", content: "foo", kind: "system" }),
    ];
    const fp = extractFingerprint(items);
    expect(fp.kindsPresent).toEqual(["retrieval", "system"]);
    expect(fp.kindRatios["system"]).toBeCloseTo(2 / 3);
    expect(fp.kindRatios["retrieval"]).toBeCloseTo(1 / 3);
  });

  it("uses 'unknown' kind when kind is undefined", () => {
    const items = [makeItem({ id: "1", content: "hello" })];
    const fp = extractFingerprint(items);
    expect(fp.kindsPresent).toEqual(["unknown"]);
    expect(fp.kindRatios["unknown"]).toBe(1);
  });

  it("computes priority and recency stats", () => {
    const items = [
      makeItem({ id: "1", content: "a", priority: 0.2, recency: 0.9 }),
      makeItem({ id: "2", content: "b", priority: 0.8, recency: 0.1 }),
    ];
    const fp = extractFingerprint(items);
    expect(fp.priorityStats.min).toBe(0.2);
    expect(fp.priorityStats.max).toBe(0.8);
    expect(fp.priorityStats.mean).toBe(0.5);
    expect(fp.recencyStats.min).toBe(0.1);
    expect(fp.recencyStats.max).toBe(0.9);
  });

  it("defaults missing priority/recency to 0.5", () => {
    const items = [makeItem({ id: "1", content: "a" })];
    const fp = extractFingerprint(items);
    expect(fp.priorityStats.mean).toBe(0.5);
    expect(fp.recencyStats.mean).toBe(0.5);
  });

  it("computes token utilization with budget", () => {
    const items = [
      makeItem({ id: "1", content: "a", tokens: 500 }),
      makeItem({ id: "2", content: "b", tokens: 300 }),
    ];
    const budget: Budget = { maxTokens: 1000 };
    const fp = extractFingerprint(items, budget);
    expect(fp.tokenUtilization).toBe(0.8);
  });

  it("caps token utilization at 1.0", () => {
    const items = [makeItem({ id: "1", content: "a", tokens: 2000 })];
    const budget: Budget = { maxTokens: 1000 };
    const fp = extractFingerprint(items, budget);
    expect(fp.tokenUtilization).toBe(1);
  });

  it("computes staleness ratio correctly", () => {
    const items = [
      makeItem({ id: "1", content: "a", recency: 0.1 }),
      makeItem({ id: "2", content: "b", recency: 0.15 }),
      makeItem({ id: "3", content: "c", recency: 0.5 }),
      makeItem({ id: "4", content: "d", recency: 0.9 }),
    ];
    const fp = extractFingerprint(items);
    // 2 out of 4 items have recency < 0.2
    expect(fp.stalenessRatio).toBe(0.5);
  });

  it("detects redundant items via Jaccard overlap", () => {
    const content = "the quick brown fox jumps over the lazy dog";
    const items = [
      makeItem({ id: "1", content }),
      makeItem({ id: "2", content }),
      makeItem({ id: "3", content: "completely different unique text here" }),
    ];
    const fp = extractFingerprint(items);
    // Items 1 and 2 are identical, so redundancy > 0
    expect(fp.redundancyEstimate).toBeGreaterThan(0);
  });

  it("reports zero redundancy for distinct items", () => {
    const items = [
      makeItem({ id: "1", content: "alpha beta gamma delta epsilon" }),
      makeItem({ id: "2", content: "zeta eta theta iota kappa lambda" }),
    ];
    const fp = extractFingerprint(items);
    expect(fp.redundancyEstimate).toBe(0);
  });

  it("handles single item", () => {
    const items = [makeItem({ id: "1", content: "hello world", kind: "code" })];
    const fp = extractFingerprint(items);
    expect(fp.itemCount).toBe(1);
    expect(fp.kindsPresent).toEqual(["code"]);
    expect(fp.redundancyEstimate).toBe(0);
  });
});

describe("compareFingerprints", () => {
  it("returns 1.0 for identical fingerprints", () => {
    const fp: Fingerprint = {
      kindsPresent: ["system"],
      kindRatios: { system: 1 },
      priorityStats: { min: 0.5, max: 0.5, mean: 0.5, std: 0 },
      recencyStats: { min: 0.5, max: 0.5, mean: 0.5, std: 0 },
      tokenUtilization: 0.8,
      itemCount: 5,
      stalenessRatio: 0.2,
      redundancyEstimate: 0.1,
    };
    expect(compareFingerprints(fp, fp)).toBeCloseTo(1.0);
  });

  it("returns lower score for very different fingerprints", () => {
    const fpA: Fingerprint = {
      kindsPresent: ["system"],
      kindRatios: { system: 1 },
      priorityStats: { min: 0.9, max: 1.0, mean: 0.95, std: 0.02 },
      recencyStats: { min: 0.9, max: 1.0, mean: 0.95, std: 0.02 },
      tokenUtilization: 0.95,
      itemCount: 20,
      stalenessRatio: 0,
      redundancyEstimate: 0,
    };
    const fpB: Fingerprint = {
      kindsPresent: ["retrieval"],
      kindRatios: { retrieval: 1 },
      priorityStats: { min: 0, max: 0.1, mean: 0.05, std: 0.02 },
      recencyStats: { min: 0, max: 0.1, mean: 0.05, std: 0.02 },
      tokenUtilization: 0.1,
      itemCount: 2,
      stalenessRatio: 1,
      redundancyEstimate: 0.9,
    };
    const similarity = compareFingerprints(fpA, fpB);
    expect(similarity).toBeLessThan(0.5);
  });

  it("handles empty fingerprints", () => {
    const empty: Fingerprint = {
      kindsPresent: [],
      kindRatios: {},
      priorityStats: { min: 0, max: 0, mean: 0, std: 0 },
      recencyStats: { min: 0, max: 0, mean: 0, std: 0 },
      tokenUtilization: 0,
      itemCount: 0,
      stalenessRatio: 0,
      redundancyEstimate: 0,
    };
    // Two empty fingerprints should be identical
    expect(compareFingerprints(empty, empty)).toBeCloseTo(1.0);
  });

  it("similarity is symmetric", () => {
    const fpA: Fingerprint = {
      kindsPresent: ["system", "code"],
      kindRatios: { system: 0.6, code: 0.4 },
      priorityStats: { min: 0.3, max: 0.9, mean: 0.6, std: 0.2 },
      recencyStats: { min: 0.4, max: 0.8, mean: 0.6, std: 0.15 },
      tokenUtilization: 0.7,
      itemCount: 10,
      stalenessRatio: 0.1,
      redundancyEstimate: 0.05,
    };
    const fpB: Fingerprint = {
      kindsPresent: ["system", "retrieval"],
      kindRatios: { system: 0.5, retrieval: 0.5 },
      priorityStats: { min: 0.2, max: 0.8, mean: 0.5, std: 0.25 },
      recencyStats: { min: 0.3, max: 0.7, mean: 0.5, std: 0.2 },
      tokenUtilization: 0.6,
      itemCount: 8,
      stalenessRatio: 0.2,
      redundancyEstimate: 0.15,
    };
    expect(compareFingerprints(fpA, fpB)).toBeCloseTo(
      compareFingerprints(fpB, fpA),
      10
    );
  });
});
