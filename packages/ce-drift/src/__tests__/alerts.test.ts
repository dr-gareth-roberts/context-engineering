import { describe, it, expect } from "vitest";
import type { DriftObservation } from "../types.js";
import type { ContextQuality } from "@context-engineering/core";
import { generateAlerts, generateRecommendation } from "../alerts.js";

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

describe("generateAlerts", () => {
  it("returns no alerts for stable observations", () => {
    const observations = Array.from({ length: 6 }, () => makeObservation());
    const { alerts } = generateAlerts(observations);
    expect(alerts).toEqual([]);
  });

  it("generates alerts when relevance degrades", () => {
    const observations = [
      makeObservation({ qualityOverrides: { overall: 0.9 } }),
      makeObservation({ qualityOverrides: { overall: 0.85 } }),
      makeObservation({ qualityOverrides: { overall: 0.7 } }),
      makeObservation({ qualityOverrides: { overall: 0.55 } }),
      makeObservation({ qualityOverrides: { overall: 0.4 } }),
      makeObservation({ qualityOverrides: { overall: 0.3 } }),
    ];
    const { alerts } = generateAlerts(observations);
    const relevanceAlert = alerts.find(a => a.dimension === "relevance");
    expect(relevanceAlert).toBeDefined();
    expect(relevanceAlert!.severity).not.toBe("healthy");
    expect(relevanceAlert!.delta).toBeLessThan(0);
  });

  it("generates alerts for multiple dimensions simultaneously", () => {
    const observations = [
      makeObservation({
        qualityOverrides: { overall: 0.9, redundancy: 0.05, diversity: 0.9 },
      }),
      makeObservation({
        qualityOverrides: { overall: 0.85, redundancy: 0.1, diversity: 0.85 },
      }),
      makeObservation({
        qualityOverrides: { overall: 0.6, redundancy: 0.4, diversity: 0.5 },
      }),
      makeObservation({
        qualityOverrides: { overall: 0.4, redundancy: 0.6, diversity: 0.3 },
      }),
      makeObservation({
        qualityOverrides: { overall: 0.3, redundancy: 0.8, diversity: 0.2 },
      }),
      makeObservation({
        qualityOverrides: { overall: 0.2, redundancy: 0.9, diversity: 0.1 },
      }),
    ];
    const { alerts } = generateAlerts(observations);
    const dimensions = alerts.map(a => a.dimension);
    expect(dimensions).toContain("relevance");
    expect(dimensions).toContain("redundancy");
    expect(dimensions).toContain("diversity");
  });

  it("populates all required fields on each alert", () => {
    const observations = [
      makeObservation({ qualityOverrides: { overall: 0.9 } }),
      makeObservation({ qualityOverrides: { overall: 0.8 } }),
      makeObservation({ qualityOverrides: { overall: 0.5 } }),
      makeObservation({ qualityOverrides: { overall: 0.3 } }),
      makeObservation({ qualityOverrides: { overall: 0.2 } }),
      makeObservation({ qualityOverrides: { overall: 0.1 } }),
    ];
    const { alerts } = generateAlerts(observations);
    const alert = alerts.find(a => a.dimension === "relevance");
    expect(alert).toBeDefined();
    expect(alert!.dimension).toBe("relevance");
    expect(typeof alert!.severity).toBe("string");
    expect(typeof alert!.currentValue).toBe("number");
    expect(typeof alert!.baselineValue).toBe("number");
    expect(typeof alert!.delta).toBe("number");
    expect(typeof alert!.trend).toBe("string");
    expect(typeof alert!.message).toBe("string");
    expect(typeof alert!.recommendation).toBe("string");
    expect(typeof alert!.observationIndex).toBe("number");
    expect(alert!.observationIndex).toBe(observations.length - 1);
  });

  it("returns dimension reports for all six dimensions", () => {
    const observations = Array.from({ length: 6 }, () => makeObservation());
    const { dimensions } = generateAlerts(observations);
    expect(Object.keys(dimensions)).toHaveLength(6);
    expect(dimensions.relevance).toBeDefined();
    expect(dimensions.redundancy).toBeDefined();
    expect(dimensions.diversity).toBeDefined();
    expect(dimensions.freshness).toBeDefined();
    expect(dimensions.utilization).toBeDefined();
    expect(dimensions.density).toBeDefined();
  });

  it("respects custom thresholds", () => {
    // Use a very tight threshold so even small drift triggers alerts
    const observations = [
      makeObservation({ qualityOverrides: { overall: 0.8 } }),
      makeObservation({ qualityOverrides: { overall: 0.78 } }),
      makeObservation({ qualityOverrides: { overall: 0.75 } }),
      makeObservation({ qualityOverrides: { overall: 0.73 } }),
      makeObservation({ qualityOverrides: { overall: 0.7 } }),
      makeObservation({ qualityOverrides: { overall: 0.68 } }),
    ];
    // With default threshold of 0.2, this mild drop is healthy
    const { alerts: defaultAlerts } = generateAlerts(observations);
    const defaultRelevance = defaultAlerts.find(
      a => a.dimension === "relevance"
    );

    // With tight threshold of 0.05, the same drop triggers an alert
    const { alerts: tightAlerts } = generateAlerts(observations, {
      relevanceDrift: 0.05,
    });
    const tightRelevance = tightAlerts.find(a => a.dimension === "relevance");
    expect(tightRelevance).toBeDefined();
    expect(tightRelevance!.severity).not.toBe("healthy");
  });
});

describe("generateRecommendation", () => {
  it("returns recommendation for each dimension at warning level", () => {
    const dimensions = [
      "relevance",
      "redundancy",
      "diversity",
      "freshness",
      "utilization",
      "density",
    ] as const;
    for (const dim of dimensions) {
      const rec = generateRecommendation(dim, "warning");
      expect(rec).toBeTruthy();
      expect(rec).toContain("Consider");
    }
  });

  it("returns urgent recommendation for critical severity", () => {
    const rec = generateRecommendation("relevance", "critical");
    expect(rec).toContain("Immediately");
  });

  it("recommendation for freshness mentions stale items", () => {
    const rec = generateRecommendation("freshness", "warning");
    expect(rec.toLowerCase()).toContain("stale");
  });

  it("recommendation for redundancy mentions dedup", () => {
    const rec = generateRecommendation("redundancy", "warning");
    expect(rec.toLowerCase()).toContain("dedup");
  });
});
