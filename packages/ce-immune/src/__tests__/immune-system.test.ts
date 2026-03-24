import { describe, it, expect, beforeEach, vi } from "vitest";
import type { ContextItem, Budget } from "@context-engineering/core";
import type { FailureRecord, ScreeningResult } from "../types.js";
import { createImmuneSystem } from "../immune-system.js";
import { resetIdCounter } from "../antibodies.js";

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

const DEFAULT_BUDGET: Budget = { maxTokens: 4000 };

function makeToxicItems(): ContextItem[] {
  return [
    makeItem({
      id: "sys",
      content: "you are a helpful assistant",
      kind: "system",
      priority: 1.0,
      recency: 1.0,
    }),
    makeItem({
      id: "stale1",
      content: "old data from archives one",
      kind: "retrieval",
      priority: 0.2,
      recency: 0.05,
    }),
    makeItem({
      id: "stale2",
      content: "old data from archives two",
      kind: "retrieval",
      priority: 0.15,
      recency: 0.08,
    }),
    makeItem({
      id: "stale3",
      content: "old data from archives three",
      kind: "retrieval",
      priority: 0.1,
      recency: 0.03,
    }),
  ];
}

function makeSafeItems(): ContextItem[] {
  return [
    makeItem({
      id: "sys",
      content: "you are a helpful assistant",
      kind: "system",
      priority: 1.0,
      recency: 1.0,
    }),
    makeItem({
      id: "fresh1",
      content: "brand new recent information about technology",
      kind: "conversation",
      priority: 0.8,
      recency: 0.95,
    }),
    makeItem({
      id: "fresh2",
      content: "another piece of recent relevant data",
      kind: "conversation",
      priority: 0.7,
      recency: 0.9,
    }),
  ];
}

function makeFailure(overrides?: Partial<FailureRecord>): FailureRecord {
  return {
    items: makeToxicItems(),
    budget: DEFAULT_BUDGET,
    symptom: "Model hallucinated outdated facts",
    diagnosis: "Context dominated by stale retrieval items",
    ...overrides,
  };
}

beforeEach(() => {
  resetIdCounter();
});

describe("createImmuneSystem", () => {
  it("starts with no antibodies", () => {
    const immune = createImmuneSystem();
    expect(immune.getAntibodies()).toEqual([]);
  });

  it("records a failure and creates an antibody", () => {
    const immune = createImmuneSystem();
    const antibody = immune.recordFailure(makeFailure());
    expect(antibody.id).toBe("ab-1");
    expect(antibody.symptom).toBe("Model hallucinated outdated facts");
    expect(immune.getAntibodies()).toHaveLength(1);
  });

  it("screens similar items and fires antibody", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());

    // Screen with items very similar to the toxic pattern
    const result = immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    expect(result.antibodiesFired).toHaveLength(1);
    expect(result.warnings.length + result.blocked.length).toBeGreaterThan(0);
  });

  it("returns safe for dissimilar items", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());

    const result = immune.screen(makeSafeItems(), DEFAULT_BUDGET);
    // Safe items should not fire the stale-pattern antibody
    expect(result.safe).toBe(true);
  });

  it("returns safe when no antibodies exist", () => {
    const immune = createImmuneSystem();
    const result = immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    expect(result.safe).toBe(true);
    expect(result.warnings).toEqual([]);
    expect(result.blocked).toEqual([]);
    expect(result.antibodiesFired).toEqual([]);
  });

  it("block severity makes result unsafe", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure({ severity: "block" }));

    const result = immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    if (result.antibodiesFired.length > 0) {
      expect(result.safe).toBe(false);
      expect(result.blocked).toHaveLength(1);
    }
  });

  it("warning severity keeps result safe", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure({ severity: "warning" }));

    const result = immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    if (result.antibodiesFired.length > 0) {
      expect(result.safe).toBe(true);
      expect(result.warnings.length).toBeGreaterThan(0);
    }
  });

  it("multiple antibodies can fire on same screen", () => {
    const immune = createImmuneSystem();

    // Record two different failures with the same pattern
    immune.recordFailure(makeFailure({ symptom: "Hallucination A" }));
    immune.recordFailure(makeFailure({ symptom: "Hallucination B" }));

    const result = immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    expect(result.antibodiesFired.length).toBe(2);
  });

  it("removeAntibody removes by ID", () => {
    const immune = createImmuneSystem();
    const ab = immune.recordFailure(makeFailure());
    expect(immune.getAntibodies()).toHaveLength(1);

    const removed = immune.removeAntibody(ab.id);
    expect(removed).toBe(true);
    expect(immune.getAntibodies()).toHaveLength(0);
  });

  it("removeAntibody returns false for unknown ID", () => {
    const immune = createImmuneSystem();
    expect(immune.removeAntibody("nonexistent")).toBe(false);
  });

  it("reset clears all state", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());
    immune.recordFailure(makeFailure());
    expect(immune.getAntibodies()).toHaveLength(2);

    immune.reset();
    expect(immune.getAntibodies()).toHaveLength(0);
  });

  it("maxAntibodies prunes oldest when exceeded", () => {
    const immune = createImmuneSystem({ maxAntibodies: 3 });

    for (let i = 0; i < 5; i++) {
      immune.recordFailure(makeFailure({ symptom: `failure-${i}` }));
    }

    const antibodies = immune.getAntibodies();
    expect(antibodies).toHaveLength(3);
    // The oldest two (failure-0, failure-1) should have been pruned
    const symptoms = antibodies.map(ab => ab.symptom);
    expect(symptoms).not.toContain("failure-0");
    expect(symptoms).not.toContain("failure-1");
  });

  it("uses custom match threshold", () => {
    // Very low threshold: even dissimilar patterns match
    const immune = createImmuneSystem({ matchThreshold: 0.01 });
    immune.recordFailure(makeFailure());

    const result = immune.screen(makeSafeItems(), DEFAULT_BUDGET);
    expect(result.antibodiesFired.length).toBeGreaterThan(0);
  });

  it("onAlert callback is invoked when issues are found", () => {
    const alertHandler = vi.fn();
    const immune = createImmuneSystem({ onAlert: alertHandler });
    immune.recordFailure(makeFailure());

    immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    expect(alertHandler).toHaveBeenCalled();
    const result: ScreeningResult = alertHandler.mock.calls[0][0];
    expect(result.antibodiesFired.length).toBeGreaterThan(0);
  });

  it("onAlert callback is not invoked when screening is clean", () => {
    const alertHandler = vi.fn();
    const immune = createImmuneSystem({ onAlert: alertHandler });
    // No failures recorded, so nothing to fire
    immune.screen(makeSafeItems(), DEFAULT_BUDGET);
    expect(alertHandler).not.toHaveBeenCalled();
  });

  it("export/import round-trip preserves state", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure({ symptom: "test-symptom" }));
    immune.recordFailure(makeFailure({ symptom: "test-symptom-2" }));

    const state = immune.exportState();
    expect(state.antibodies).toHaveLength(2);
    expect(state.failureCount).toBe(2);

    const immune2 = createImmuneSystem();
    immune2.importState(state);
    expect(immune2.getAntibodies()).toHaveLength(2);
    expect(immune2.getAntibodies()[0].symptom).toBe("test-symptom");
  });

  it("importState respects maxAntibodies", () => {
    const immune = createImmuneSystem({ maxAntibodies: 2 });

    const state = {
      antibodies: [
        {
          id: "ab-old",
          pattern: {
            kindsPresent: [],
            kindRatios: {},
            priorityStats: { min: 0, max: 0, mean: 0, std: 0 },
            recencyStats: { min: 0, max: 0, mean: 0, std: 0 },
            tokenUtilization: 0,
            itemCount: 0,
            stalenessRatio: 0,
            redundancyEstimate: 0,
          },
          symptom: "old",
          diagnosis: "old",
          severity: "warning" as const,
          createdAt: 1000,
          matchThreshold: 0.7,
        },
        {
          id: "ab-mid",
          pattern: {
            kindsPresent: [],
            kindRatios: {},
            priorityStats: { min: 0, max: 0, mean: 0, std: 0 },
            recencyStats: { min: 0, max: 0, mean: 0, std: 0 },
            tokenUtilization: 0,
            itemCount: 0,
            stalenessRatio: 0,
            redundancyEstimate: 0,
          },
          symptom: "mid",
          diagnosis: "mid",
          severity: "warning" as const,
          createdAt: 2000,
          matchThreshold: 0.7,
        },
        {
          id: "ab-new",
          pattern: {
            kindsPresent: [],
            kindRatios: {},
            priorityStats: { min: 0, max: 0, mean: 0, std: 0 },
            recencyStats: { min: 0, max: 0, mean: 0, std: 0 },
            tokenUtilization: 0,
            itemCount: 0,
            stalenessRatio: 0,
            redundancyEstimate: 0,
          },
          symptom: "new",
          diagnosis: "new",
          severity: "warning" as const,
          createdAt: 3000,
          matchThreshold: 0.7,
        },
      ],
      failureCount: 3,
    };

    immune.importState(state);
    const antibodies = immune.getAntibodies();
    expect(antibodies).toHaveLength(2);
    // Oldest should have been pruned
    expect(antibodies.find(ab => ab.id === "ab-old")).toBeUndefined();
  });

  it("exported state is a deep copy", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());

    const state = immune.exportState();
    state.antibodies.push(state.antibodies[0]);
    // Original should be unaffected
    expect(immune.getAntibodies()).toHaveLength(1);
  });

  it("getAntibodies returns a copy", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());

    const abs = immune.getAntibodies();
    abs.pop();
    expect(immune.getAntibodies()).toHaveLength(1);
  });

  it("handles screening with empty items", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());

    const result = immune.screen([], DEFAULT_BUDGET);
    // Empty items produce a very different fingerprint, should not match
    expect(result.safe).toBe(true);
  });

  it("handles screening with all same kind", () => {
    const immune = createImmuneSystem({ matchThreshold: 0.5 });
    const sameKindItems = Array.from({ length: 5 }, (_, i) =>
      makeItem({
        id: `item-${i}`,
        content: `content number ${i} with unique words variant${i}`,
        kind: "system",
        priority: 0.5,
        recency: 0.5,
      })
    );
    immune.recordFailure({
      items: sameKindItems,
      budget: DEFAULT_BUDGET,
      symptom: "Monotone context",
    });

    const result = immune.screen(sameKindItems, DEFAULT_BUDGET);
    expect(result.antibodiesFired.length).toBeGreaterThan(0);
  });

  it("screening alert contains correct fields", () => {
    const immune = createImmuneSystem();
    immune.recordFailure(makeFailure());

    const result = immune.screen(makeToxicItems(), DEFAULT_BUDGET);
    if (result.warnings.length > 0) {
      const alert = result.warnings[0];
      expect(alert.antibodyId).toBeDefined();
      expect(typeof alert.similarity).toBe("number");
      expect(alert.symptom).toBe("Model hallucinated outdated facts");
      expect(alert.diagnosis).toBe(
        "Context dominated by stale retrieval items"
      );
      expect(alert.severity).toBe("warning");
    }
  });
});
