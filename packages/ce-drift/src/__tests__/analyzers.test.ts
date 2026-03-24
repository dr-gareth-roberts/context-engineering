import { describe, it, expect } from "vitest";
import type { DriftObservation } from "../types.js";
import type { ContextQuality } from "@context-engineering/core";
import {
  analyzeRelevanceDrift,
  analyzeRedundancyCreep,
  analyzeTopicDrift,
  analyzeStaleness,
  analyzeUtilization,
  analyzeDensityDrop,
  classifySeverity,
} from "../analyzers.js";

/**
 * Helper: build a minimal DriftObservation with overrides.
 */
function makeObservation(
  overrides: Partial<DriftObservation> & {
    qualityOverrides?: Partial<ContextQuality>;
  } = {}
): DriftObservation {
  const { qualityOverrides, ...rest } = overrides;
  return {
    timestamp: Date.now(),
    quality: {
      itemCount: 5,
      totalTokens: 500,
      density: 0.6,
      diversity: 0.7,
      freshness: 0.8,
      redundancy: 0.1,
      overall: 0.75,
      ...qualityOverrides,
    },
    itemCount: 5,
    totalTokens: 500,
    budgetUtilization: 0.8,
    staleItemCount: 0,
    topKinds: { code: 3, docs: 2 },
    ...rest,
  };
}

describe("classifySeverity", () => {
  it("returns healthy when delta is below half the threshold", () => {
    expect(classifySeverity(0.05, 0.2)).toBe("healthy");
  });

  it("returns warning when delta is between half and full threshold", () => {
    expect(classifySeverity(0.15, 0.2)).toBe("warning");
  });

  it("returns critical when delta meets or exceeds threshold", () => {
    expect(classifySeverity(0.2, 0.2)).toBe("critical");
    expect(classifySeverity(0.3, 0.2)).toBe("critical");
  });

  it("uses absolute value of delta", () => {
    expect(classifySeverity(-0.15, 0.2)).toBe("warning");
    expect(classifySeverity(-0.25, 0.2)).toBe("critical");
  });
});

describe("analyzeRelevanceDrift", () => {
  it("returns empty report for no observations", () => {
    const report = analyzeRelevanceDrift([], 0.2);
    expect(report.severity).toBe("healthy");
    expect(report.history).toEqual([]);
    expect(report.delta).toBe(0);
  });

  it("detects declining overall quality as relevance drift", () => {
    const observations = [
      makeObservation({ qualityOverrides: { overall: 0.8 } }),
      makeObservation({ qualityOverrides: { overall: 0.75 } }),
      makeObservation({ qualityOverrides: { overall: 0.7 } }),
      makeObservation({ qualityOverrides: { overall: 0.6 } }),
      makeObservation({ qualityOverrides: { overall: 0.5 } }),
      makeObservation({ qualityOverrides: { overall: 0.4 } }),
    ];
    const report = analyzeRelevanceDrift(observations, 0.2);
    expect(report.severity).not.toBe("healthy");
    expect(report.trend).toBe("degrading");
    expect(report.delta).toBeLessThan(0);
  });

  it("stays healthy when quality is stable", () => {
    const observations = Array.from({ length: 6 }, () =>
      makeObservation({ qualityOverrides: { overall: 0.75 } })
    );
    const report = analyzeRelevanceDrift(observations, 0.2);
    expect(report.severity).toBe("healthy");
    expect(report.trend).toBe("stable");
  });

  it("recognizes improving trend", () => {
    const observations = [
      makeObservation({ qualityOverrides: { overall: 0.4 } }),
      makeObservation({ qualityOverrides: { overall: 0.5 } }),
      makeObservation({ qualityOverrides: { overall: 0.6 } }),
      makeObservation({ qualityOverrides: { overall: 0.7 } }),
      makeObservation({ qualityOverrides: { overall: 0.8 } }),
      makeObservation({ qualityOverrides: { overall: 0.9 } }),
    ];
    const report = analyzeRelevanceDrift(observations, 0.2);
    expect(report.trend).toBe("improving");
  });
});

describe("analyzeRedundancyCreep", () => {
  it("detects rising redundancy", () => {
    const observations = [
      makeObservation({ qualityOverrides: { redundancy: 0.1 } }),
      makeObservation({ qualityOverrides: { redundancy: 0.15 } }),
      makeObservation({ qualityOverrides: { redundancy: 0.3 } }),
      makeObservation({ qualityOverrides: { redundancy: 0.5 } }),
      makeObservation({ qualityOverrides: { redundancy: 0.7 } }),
      makeObservation({ qualityOverrides: { redundancy: 0.8 } }),
    ];
    const report = analyzeRedundancyCreep(observations, 0.4);
    expect(report.severity).not.toBe("healthy");
    expect(report.trend).toBe("degrading");
    expect(report.delta).toBeGreaterThan(0);
  });

  it("stays healthy when redundancy is low and stable", () => {
    const observations = Array.from({ length: 6 }, () =>
      makeObservation({ qualityOverrides: { redundancy: 0.1 } })
    );
    const report = analyzeRedundancyCreep(observations, 0.4);
    expect(report.severity).toBe("healthy");
  });
});

describe("analyzeTopicDrift", () => {
  it("detects declining diversity", () => {
    const observations = [
      makeObservation({ qualityOverrides: { diversity: 0.9 } }),
      makeObservation({ qualityOverrides: { diversity: 0.85 } }),
      makeObservation({ qualityOverrides: { diversity: 0.7 } }),
      makeObservation({ qualityOverrides: { diversity: 0.5 } }),
      makeObservation({ qualityOverrides: { diversity: 0.4 } }),
      makeObservation({ qualityOverrides: { diversity: 0.3 } }),
    ];
    const report = analyzeTopicDrift(observations, 0.3);
    expect(report.severity).not.toBe("healthy");
    expect(report.delta).toBeLessThan(0);
  });
});

describe("analyzeStaleness", () => {
  it("detects increasing stale item ratio", () => {
    const observations = [
      makeObservation({ itemCount: 10, staleItemCount: 1 }),
      makeObservation({ itemCount: 10, staleItemCount: 2 }),
      makeObservation({ itemCount: 10, staleItemCount: 4 }),
      makeObservation({ itemCount: 10, staleItemCount: 6 }),
      makeObservation({ itemCount: 10, staleItemCount: 8 }),
      makeObservation({ itemCount: 10, staleItemCount: 9 }),
    ];
    const report = analyzeStaleness(observations, 0.5);
    expect(report.severity).not.toBe("healthy");
    expect(report.delta).toBeGreaterThan(0);
  });

  it("handles zero item count without division error", () => {
    const observations = [makeObservation({ itemCount: 0, staleItemCount: 0 })];
    const report = analyzeStaleness(observations, 0.5);
    expect(report.current).toBe(0);
  });
});

describe("analyzeUtilization", () => {
  it("detects dropping budget utilization", () => {
    const observations = [
      makeObservation({ budgetUtilization: 0.9 }),
      makeObservation({ budgetUtilization: 0.85 }),
      makeObservation({ budgetUtilization: 0.7 }),
      makeObservation({ budgetUtilization: 0.5 }),
      makeObservation({ budgetUtilization: 0.3 }),
      makeObservation({ budgetUtilization: 0.2 }),
    ];
    const report = analyzeUtilization(observations, 0.5);
    expect(report.severity).not.toBe("healthy");
    expect(report.delta).toBeLessThan(0);
  });
});

describe("analyzeDensityDrop", () => {
  it("detects declining information density", () => {
    const observations = [
      makeObservation({ qualityOverrides: { density: 0.8 } }),
      makeObservation({ qualityOverrides: { density: 0.7 } }),
      makeObservation({ qualityOverrides: { density: 0.55 } }),
      makeObservation({ qualityOverrides: { density: 0.4 } }),
      makeObservation({ qualityOverrides: { density: 0.3 } }),
      makeObservation({ qualityOverrides: { density: 0.2 } }),
    ];
    const report = analyzeDensityDrop(observations, 0.25);
    expect(report.severity).not.toBe("healthy");
    expect(report.trend).toBe("degrading");
  });

  it("returns history of density values", () => {
    const observations = [
      makeObservation({ qualityOverrides: { density: 0.8 } }),
      makeObservation({ qualityOverrides: { density: 0.7 } }),
      makeObservation({ qualityOverrides: { density: 0.6 } }),
    ];
    const report = analyzeDensityDrop(observations, 0.25);
    expect(report.history).toEqual([0.8, 0.7, 0.6]);
  });
});

describe("single observation", () => {
  it("single observation returns a report with no drift", () => {
    const observations = [makeObservation()];
    const report = analyzeRelevanceDrift(observations, 0.2);
    expect(report.delta).toBe(0);
    expect(report.severity).toBe("healthy");
    expect(report.trend).toBe("stable");
  });
});

describe("all-identical observations", () => {
  it("reports stable trend and healthy severity for identical observations", () => {
    const observations = Array.from({ length: 10 }, () => makeObservation());
    const relevance = analyzeRelevanceDrift(observations, 0.2);
    const redundancy = analyzeRedundancyCreep(observations, 0.4);
    const diversity = analyzeTopicDrift(observations, 0.3);

    expect(relevance.trend).toBe("stable");
    expect(relevance.severity).toBe("healthy");
    expect(redundancy.trend).toBe("stable");
    expect(redundancy.severity).toBe("healthy");
    expect(diversity.trend).toBe("stable");
    expect(diversity.severity).toBe("healthy");
  });
});
