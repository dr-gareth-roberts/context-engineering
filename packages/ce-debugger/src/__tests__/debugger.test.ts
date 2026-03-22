import { describe, it, expect } from "vitest";
import { createContextDebugger } from "../debugger.js";
import type {
  ContextPack,
  ContextTrace,
  ContextItem,
} from "@context-engineering/core";

function makeItem(
  overrides: Partial<ContextItem> & { id: string; content: string }
): ContextItem {
  return { tokens: 10, ...overrides };
}

function makePack(overrides: Partial<ContextPack> = {}): ContextPack {
  return {
    budget: { maxTokens: 1000 },
    selected: [],
    dropped: [],
    totalTokens: 0,
    ...overrides,
  };
}

describe("createContextDebugger.diagnose", () => {
  it("diagnoses high redundancy", () => {
    // Create items with very similar content to trigger redundancy
    const similar = Array.from({ length: 10 }, (_, i) =>
      makeItem({
        id: `item-${i}`,
        content: "the quick brown fox jumps over the lazy dog repeatedly",
        tokens: 10,
        recency: 8,
      })
    );

    const pack = makePack({ selected: similar, totalTokens: 100 });
    const debugger_ = createContextDebugger({
      qualityThresholds: { maxRedundancy: 0.3 },
    });
    const diagnosis = debugger_.diagnose(pack);

    const redundancyIssue = diagnosis.issues.find(
      i => i.category === "redundancy"
    );
    expect(redundancyIssue).toBeDefined();
    expect(redundancyIssue?.severity).toBe("warning");
  });

  it("diagnoses stale context (low freshness)", () => {
    const staleItems = Array.from({ length: 5 }, (_, i) =>
      makeItem({
        id: `stale-${i}`,
        content: `old content number ${i} about various topics and things`,
        tokens: 20,
        recency: 1, // very stale
      })
    );

    const pack = makePack({ selected: staleItems, totalTokens: 100 });
    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(pack);

    const staleIssue = diagnosis.issues.find(
      i => i.category === "stale-context"
    );
    expect(staleIssue).toBeDefined();
    expect(staleIssue?.severity).toBe("warning");
  });

  it("diagnoses low diversity", () => {
    // Items with very repetitive bigram structure
    const narrow = Array.from({ length: 5 }, (_, i) =>
      makeItem({
        id: `narrow-${i}`,
        content: "foo bar foo bar foo bar foo bar",
        tokens: 10,
        recency: 8,
      })
    );

    const pack = makePack({ selected: narrow, totalTokens: 50 });
    const debugger_ = createContextDebugger({
      qualityThresholds: { minDiversity: 0.9 },
    });
    const diagnosis = debugger_.diagnose(pack);

    const diversityIssue = diagnosis.issues.find(
      i => i.category === "low-diversity"
    );
    expect(diversityIssue).toBeDefined();
  });

  it("diagnoses dropped high-priority items as critical", () => {
    const selected = [
      makeItem({ id: "low", content: "low priority item", priority: 3 }),
    ];
    const dropped = [
      makeItem({
        id: "critical-1",
        content: "critical context that was dropped",
        priority: 9,
      }),
      makeItem({
        id: "critical-2",
        content: "another critical dropped item",
        priority: 8,
      }),
    ];

    const pack = makePack({ selected, dropped, totalTokens: 10 });
    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(pack);

    const priorityIssue = diagnosis.issues.find(
      i => i.category === "wrong-priorities"
    );
    expect(priorityIssue).toBeDefined();
    expect(priorityIssue?.severity).toBe("critical");
    expect(diagnosis.overallHealth).toBe("critical");
  });

  it("diagnoses missing relevant context when query provided", () => {
    const selected = [
      makeItem({ id: "sel", content: "unrelated topic about cooking recipes" }),
    ];
    const dropped = [
      makeItem({
        id: "rel-1",
        content: "typescript compiler configuration and setup guide",
      }),
      makeItem({
        id: "rel-2",
        content: "typescript type checking with strict mode enabled",
      }),
    ];

    const pack = makePack({ selected, dropped, totalTokens: 10 });
    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(pack, {
      query: "typescript configuration",
    });

    const missingIssue = diagnosis.issues.find(
      i => i.category === "missing-context"
    );
    expect(missingIssue).toBeDefined();
    expect(missingIssue?.severity).toBe("warning");
  });

  it("returns good health for well-balanced pack", () => {
    const items = [
      makeItem({
        id: "a",
        content: "first topic about machine learning algorithms",
        recency: 8,
        kind: "code",
        tokens: 100,
      }),
      makeItem({
        id: "b",
        content: "second topic covering database optimization techniques",
        recency: 7,
        kind: "docs",
        tokens: 100,
      }),
      makeItem({
        id: "c",
        content: "third subject regarding frontend user interface design",
        recency: 9,
        kind: "notes",
        tokens: 100,
      }),
      makeItem({
        id: "d",
        content: "fourth area discussing cloud infrastructure deployment",
        recency: 6,
        kind: "config",
        tokens: 100,
      }),
      makeItem({
        id: "e",
        content: "fifth section about security authentication patterns",
        recency: 8,
        kind: "review",
        tokens: 100,
      }),
    ];

    const pack = makePack({
      selected: items,
      totalTokens: 500,
      budget: { maxTokens: 800 },
    });
    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(pack);

    expect(diagnosis.overallHealth).toBe("good");
    expect(
      diagnosis.issues.filter(i => i.severity === "critical")
    ).toHaveLength(0);
    expect(diagnosis.issues.filter(i => i.severity === "warning")).toHaveLength(
      0
    );
  });

  it("returns critical when any critical issue present", () => {
    const dropped = [
      makeItem({ id: "hp", content: "high priority dropped", priority: 10 }),
    ];
    const pack = makePack({ selected: [], dropped, totalTokens: 0 });
    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(pack);

    expect(diagnosis.overallHealth).toBe("critical");
  });

  it("handles empty pack gracefully", () => {
    const pack = makePack({ selected: [], dropped: [], totalTokens: 0 });
    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(pack);

    expect(diagnosis.quality.itemCount).toBe(0);
    expect(diagnosis.droppedAnalysis.totalDropped).toBe(0);
    // Should not crash, health can be good or info-level
    expect(diagnosis.overallHealth).toBeDefined();
  });

  it("works with ContextTrace inputs", () => {
    const items = [
      makeItem({
        id: "traced",
        content: "traced item with some content about testing",
        recency: 8,
        tokens: 50,
      }),
    ];
    const trace: ContextTrace = {
      pack: makePack({
        selected: items,
        totalTokens: 50,
        budget: { maxTokens: 100 },
      }),
      steps: [
        {
          id: "traced",
          decision: "include",
          tokens: 50,
          score: 5,
          reason: "fits_budget",
        },
      ],
      createdAt: new Date().toISOString(),
    };

    const debugger_ = createContextDebugger();
    const diagnosis = debugger_.diagnose(trace);

    expect(diagnosis.quality.itemCount).toBe(1);
    expect(diagnosis.droppedAnalysis.totalDropped).toBe(0);
  });
});
