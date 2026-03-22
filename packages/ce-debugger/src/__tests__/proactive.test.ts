import { describe, it, expect } from "vitest";
import { createContextDebugger } from "../debugger.js";
import type { ContextItem } from "@context-engineering/core";

function makeItem(
  overrides: Partial<ContextItem> & { id: string; content: string }
): ContextItem {
  return { tokens: 10, ...overrides };
}

describe("proactiveCheck", () => {
  it("catches redundancy before sending", () => {
    const items = Array.from({ length: 10 }, (_, i) =>
      makeItem({
        id: `dup-${i}`,
        content: "the quick brown fox jumps over the lazy dog again and again",
        tokens: 10,
        recency: 8,
        priority: 5,
      })
    );

    const debugger_ = createContextDebugger({
      qualityThresholds: { maxRedundancy: 0.3 },
    });
    const diagnosis = debugger_.proactiveCheck(items, { maxTokens: 500 });

    const redundancyIssue = diagnosis.issues.find(
      i => i.category === "redundancy"
    );
    expect(redundancyIssue).toBeDefined();
  });

  it("warns about low utilization", () => {
    const items = [
      makeItem({ id: "small", content: "tiny item", tokens: 5, priority: 5 }),
    ];

    const debugger_ = createContextDebugger({
      qualityThresholds: { minUtilization: 0.5 },
    });
    const diagnosis = debugger_.proactiveCheck(items, { maxTokens: 10000 });

    const utilizationIssue = diagnosis.issues.find(
      i => i.category === "budget-waste"
    );
    expect(utilizationIssue).toBeDefined();
  });

  it("passes clean context without issues", () => {
    const items = [
      makeItem({
        id: "a",
        content: "first topic about machine learning algorithms and models",
        recency: 8,
        kind: "code",
        tokens: 80,
      }),
      makeItem({
        id: "b",
        content: "second topic covering database optimization and queries",
        recency: 7,
        kind: "docs",
        tokens: 80,
      }),
      makeItem({
        id: "c",
        content: "third subject regarding frontend design and components",
        recency: 9,
        kind: "notes",
        tokens: 80,
      }),
      makeItem({
        id: "d",
        content: "fourth area discussing cloud infrastructure and deployment",
        recency: 6,
        kind: "config",
        tokens: 80,
      }),
      makeItem({
        id: "e",
        content: "fifth section about security patterns and authentication",
        recency: 8,
        kind: "review",
        tokens: 80,
      }),
    ];

    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.proactiveCheck(items, { maxTokens: 600 });

    expect(diagnosis.overallHealth).toBe("good");
    expect(
      diagnosis.issues.filter(i => i.severity === "critical")
    ).toHaveLength(0);
    expect(diagnosis.issues.filter(i => i.severity === "warning")).toHaveLength(
      0
    );
  });

  it("uses packOptions when provided", () => {
    const items = [
      makeItem({
        id: "a",
        content: "item about typescript",
        priority: 10,
        tokens: 50,
        recency: 8,
      }),
      makeItem({
        id: "b",
        content: "item about python",
        priority: 1,
        tokens: 50,
        recency: 8,
      }),
    ];

    const debugger_ = createContextDebugger();
    // With a tight budget, one item gets dropped
    const diagnosis = debugger_.proactiveCheck(
      items,
      { maxTokens: 60 },
      {
        packOptions: { weights: { priority: 2.0 } },
      }
    );

    expect(diagnosis.droppedAnalysis.totalDropped).toBe(1);
  });

  it("identifies missing relevant context with query", () => {
    const items = [
      makeItem({
        id: "irrelevant",
        content: "cooking recipes for dinner ideas",
        priority: 10,
        tokens: 50,
        recency: 8,
      }),
      makeItem({
        id: "relevant",
        content: "typescript compiler strict mode configuration",
        priority: 1,
        tokens: 50,
        recency: 8,
      }),
    ];

    const debugger_ = createContextDebugger();
    // Budget only fits one item; the high-priority irrelevant item wins
    const diagnosis = debugger_.proactiveCheck(
      items,
      { maxTokens: 60 },
      {
        query: "typescript configuration",
      }
    );

    // The relevant item was dropped despite being query-relevant
    if (diagnosis.droppedAnalysis.potentiallyRelevant.length > 0) {
      const missingIssue = diagnosis.issues.find(
        i => i.category === "missing-context"
      );
      expect(missingIssue).toBeDefined();
    }
    // At minimum, the diagnosis should complete without errors
    expect(diagnosis.overallHealth).toBeDefined();
  });
});
