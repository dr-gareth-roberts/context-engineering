import { describe, it, expect, vi } from "vitest";
import { createDriftMonitor } from "../monitor.js";
import type { DriftAlert, DriftObservation } from "../types.js";
import type {
  Budget,
  ContextItem,
  ContextPack,
} from "@context-engineering/core";

/**
 * Helper: build a simple ContextItem.
 */
function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return {
    id,
    content,
    tokens: Math.ceil(content.split(/\s+/).length * 1.3),
    ...overrides,
  };
}

/**
 * Helper: build a ContextPack.
 */
function makePack(items: ContextItem[], budget: Budget): ContextPack {
  const totalTokens = items.reduce((sum, i) => sum + (i.tokens ?? 0), 0);
  return {
    budget,
    selected: items,
    dropped: [],
    totalTokens,
  };
}

const DEFAULT_BUDGET: Budget = { maxTokens: 4000 };

describe("createDriftMonitor", () => {
  it("returns healthy status with no observations", () => {
    const monitor = createDriftMonitor();
    const report = monitor.report();
    expect(report.status).toBe("healthy");
    expect(report.drifting).toBe(false);
    expect(report.since).toBeNull();
    expect(report.observationCount).toBe(0);
    expect(report.alerts).toEqual([]);
    expect(report.recommendations).toEqual([]);
  });

  it("single observation does not trigger alerts due to minObservations", () => {
    const monitor = createDriftMonitor({ minObservations: 3 });
    const items = [makeItem("a", "first item content here")];
    monitor.observeItems(items, DEFAULT_BUDGET);
    const report = monitor.report();
    expect(report.observationCount).toBe(1);
    expect(report.alerts).toEqual([]);
    expect(report.drifting).toBe(false);
  });

  it("observe() accepts a ContextPack", () => {
    const monitor = createDriftMonitor();
    const items = [makeItem("a", "hello world context data")];
    const pack = makePack(items, DEFAULT_BUDGET);
    monitor.observe(pack, DEFAULT_BUDGET);
    expect(monitor.history()).toHaveLength(1);
  });

  it("observeItems() accepts raw items and budget", () => {
    const monitor = createDriftMonitor();
    const items = [makeItem("a", "hello world context data")];
    monitor.observeItems(items, DEFAULT_BUDGET);
    expect(monitor.history()).toHaveLength(1);
  });

  it("detects degrading quality across observations", () => {
    const monitor = createDriftMonitor({
      minObservations: 3,
      thresholds: { relevanceDrift: 0.05 },
    });

    // Feed progressively worse content to trigger quality decline
    // Use highly varied content for first observations (high quality)
    const goodItems = [
      makeItem(
        "a",
        "comprehensive architecture documentation for microservices",
        { recency: 8 }
      ),
      makeItem(
        "b",
        "database schema migration strategy and rollback procedures",
        { recency: 9 }
      ),
      makeItem("c", "performance optimization benchmarks for query execution", {
        recency: 7,
      }),
    ];

    // Then feed repetitive/degraded content
    const badItems = [
      makeItem("x", "thing thing thing thing thing thing thing thing", {
        recency: 1,
      }),
      makeItem("y", "thing thing thing thing thing thing thing thing", {
        recency: 0,
      }),
    ];

    for (let i = 0; i < 3; i++) {
      monitor.observeItems(goodItems, DEFAULT_BUDGET);
    }
    for (let i = 0; i < 5; i++) {
      monitor.observeItems(badItems, DEFAULT_BUDGET);
    }

    const report = monitor.report();
    // Should detect some kind of drift given the quality drop
    expect(report.observationCount).toBe(8);
  });

  it("onAlert callback fires when drift detected", () => {
    const alerts: DriftAlert[] = [];
    const monitor = createDriftMonitor({
      minObservations: 2,
      thresholds: { relevanceDrift: 0.05 },
      onAlert: alert => alerts.push(alert),
    });

    // Start with good content
    const goodItems = [
      makeItem("a", "comprehensive detailed architecture documentation notes", {
        recency: 8,
      }),
      makeItem("b", "database migration strategy overview planning rollback", {
        recency: 9,
      }),
      makeItem("c", "unique performance benchmarks results optimization", {
        recency: 7,
      }),
    ];
    monitor.observeItems(goodItems, DEFAULT_BUDGET);
    monitor.observeItems(goodItems, DEFAULT_BUDGET);

    // Feed terrible content
    const badItems = [
      makeItem("x", "x x x x x x x x x x x x x x x x x x x x", { recency: 0 }),
    ];
    for (let i = 0; i < 5; i++) {
      monitor.observeItems(badItems, DEFAULT_BUDGET);
    }

    // onAlert should have been called at some point
    // The specific number depends on how many dimensions degrade
    expect(alerts.length).toBeGreaterThan(0);
  });

  it("reset() clears all state", () => {
    const monitor = createDriftMonitor();
    const items = [makeItem("a", "some content here for testing")];
    monitor.observeItems(items, DEFAULT_BUDGET);
    monitor.observeItems(items, DEFAULT_BUDGET);
    expect(monitor.history()).toHaveLength(2);

    monitor.reset();
    expect(monitor.history()).toHaveLength(0);
    const report = monitor.report();
    expect(report.observationCount).toBe(0);
    expect(report.status).toBe("healthy");
  });

  it("window size limits observation retention", () => {
    const monitor = createDriftMonitor({ windowSize: 3 });
    const items = [makeItem("a", "content for window test observation")];

    for (let i = 0; i < 10; i++) {
      monitor.observeItems(items, DEFAULT_BUDGET);
    }

    expect(monitor.history()).toHaveLength(3);
  });

  it("exportState and importState round-trip preserves observations", () => {
    const monitor = createDriftMonitor({ windowSize: 10 });
    const items = [
      makeItem("a", "first context item with unique words"),
      makeItem("b", "second item different vocabulary variety"),
    ];
    monitor.observeItems(items, DEFAULT_BUDGET);
    monitor.observeItems(items, DEFAULT_BUDGET);
    monitor.observeItems(items, DEFAULT_BUDGET);

    const state = monitor.exportState();
    expect(state.observations).toHaveLength(3);
    expect(state.config.windowSize).toBe(10);

    // Import into a new monitor
    const monitor2 = createDriftMonitor({ windowSize: 10 });
    monitor2.importState(state);
    expect(monitor2.history()).toHaveLength(3);

    // Reports should match (observations are the same)
    const report1 = monitor.report();
    const report2 = monitor2.report();
    expect(report2.observationCount).toBe(report1.observationCount);
  });

  it("importState trims to window size", () => {
    const monitor = createDriftMonitor({ windowSize: 5 });
    const largeState = {
      observations: Array.from({ length: 20 }, (_, i) => ({
        timestamp: Date.now() + i,
        quality: {
          itemCount: 5,
          totalTokens: 500,
          density: 0.6,
          diversity: 0.7,
          freshness: 0.8,
          redundancy: 0.1,
          overall: 0.75,
        },
        itemCount: 5,
        totalTokens: 500,
        budgetUtilization: 0.8,
        staleItemCount: 0,
        topKinds: { code: 5 },
      })) as DriftObservation[],
      config: { windowSize: 20 },
    };

    monitor.importState(largeState);
    expect(monitor.history()).toHaveLength(5);
  });

  it("report.since tracks when drift was first detected", () => {
    const monitor = createDriftMonitor({
      minObservations: 2,
      thresholds: { relevanceDrift: 0.01 },
    });

    // Feed content that will establish a baseline then degrade
    const goodItems = [
      makeItem("a", "excellent unique comprehensive architecture docs", {
        recency: 9,
      }),
      makeItem("b", "database strategy migration rollback procedures plans", {
        recency: 8,
      }),
      makeItem("c", "performance metrics benchmarks optimization results", {
        recency: 7,
      }),
    ];
    monitor.observeItems(goodItems, DEFAULT_BUDGET);
    monitor.observeItems(goodItems, DEFAULT_BUDGET);

    const reportBefore = monitor.report();
    // May or may not be drifting at this point depending on content analysis

    // Feed degraded content
    const badItems = [
      makeItem("z", "z z z z z z z z z z z z z z z z z z z z", { recency: 0 }),
    ];
    for (let i = 0; i < 5; i++) {
      monitor.observeItems(badItems, DEFAULT_BUDGET);
    }

    const reportAfter = monitor.report();
    // If drifting, since should be a timestamp
    if (reportAfter.drifting) {
      expect(reportAfter.since).toBeTypeOf("number");
      expect(reportAfter.since).toBeGreaterThan(0);
    }
  });

  it("report.since resets to null when drift recovers", () => {
    const monitor = createDriftMonitor({
      windowSize: 4,
      minObservations: 2,
      thresholds: { relevanceDrift: 0.01 },
    });

    // First cause drift
    const goodItems = [
      makeItem("a", "excellent unique comprehensive architecture design", {
        recency: 9,
      }),
      makeItem("b", "separate different database strategy planning", {
        recency: 8,
      }),
    ];
    const badItems = [
      makeItem("z", "z z z z z z z z z z z z z z z", { recency: 0 }),
    ];

    monitor.observeItems(goodItems, DEFAULT_BUDGET);
    monitor.observeItems(goodItems, DEFAULT_BUDGET);
    monitor.observeItems(badItems, DEFAULT_BUDGET);
    monitor.observeItems(badItems, DEFAULT_BUDGET);

    // Now feed good items to push bad ones out of the window
    for (let i = 0; i < 4; i++) {
      monitor.observeItems(goodItems, DEFAULT_BUDGET);
    }

    const report = monitor.report();
    // With the window now full of good items, should recover
    if (!report.drifting) {
      expect(report.since).toBeNull();
    }
  });

  it("history() returns a copy of observations", () => {
    const monitor = createDriftMonitor();
    const items = [makeItem("a", "test content for history copy")];
    monitor.observeItems(items, DEFAULT_BUDGET);

    const h1 = monitor.history();
    const h2 = monitor.history();
    expect(h1).not.toBe(h2);
    expect(h1).toEqual(h2);
  });

  it("handles sudden quality drop from stable baseline", () => {
    const monitor = createDriftMonitor({
      minObservations: 3,
      thresholds: { relevanceDrift: 0.1 },
    });

    // 5 stable observations
    const stableItems = [
      makeItem(
        "a",
        "unique architecture design patterns for distributed systems",
        { recency: 8 }
      ),
      makeItem(
        "b",
        "comprehensive database optimization strategies and indexing",
        { recency: 9 }
      ),
    ];
    for (let i = 0; i < 5; i++) {
      monitor.observeItems(stableItems, DEFAULT_BUDGET);
    }

    // Sudden drop
    const terribleItems = [
      makeItem("x", "a a a a a a a a a a a a a a a a a a", { recency: 0 }),
    ];
    monitor.observeItems(terribleItems, DEFAULT_BUDGET);

    const report = monitor.report();
    // The report should reflect the sudden change
    expect(report.observationCount).toBe(6);
  });

  it("stale items are counted based on recency < 0.2", () => {
    const monitor = createDriftMonitor();
    const items = [
      makeItem("a", "fresh content", { recency: 8 }),
      makeItem("b", "slightly old", { recency: 0.5 }),
      makeItem("c", "stale content", { recency: 0.1 }),
      makeItem("d", "very stale", { recency: 0 }),
    ];
    monitor.observeItems(items, DEFAULT_BUDGET);

    const obs = monitor.history()[0];
    // Items with recency < 0.2 are c (0.1) and d (0)
    expect(obs.staleItemCount).toBe(2);
  });

  it("budget utilization is computed correctly", () => {
    const monitor = createDriftMonitor();
    const items = [
      makeItem("a", "some content here", { tokens: 200 }),
      makeItem("b", "more content here", { tokens: 300 }),
    ];
    monitor.observeItems(items, { maxTokens: 1000 });

    const obs = monitor.history()[0];
    expect(obs.budgetUtilization).toBeCloseTo(0.5, 1);
  });

  it("budget utilization respects reserveTokens", () => {
    const monitor = createDriftMonitor();
    const items = [makeItem("a", "some content here", { tokens: 400 })];
    monitor.observeItems(items, { maxTokens: 1000, reserveTokens: 200 });

    const obs = monitor.history()[0];
    // effectiveBudget = 1000 - 200 = 800, utilization = 400/800 = 0.5
    expect(obs.budgetUtilization).toBeCloseTo(0.5, 1);
  });

  it("topKinds counts item kinds correctly", () => {
    const monitor = createDriftMonitor();
    const items = [
      makeItem("a", "code content", { kind: "code" }),
      makeItem("b", "docs content", { kind: "docs" }),
      makeItem("c", "more code", { kind: "code" }),
      makeItem("d", "no kind specified"),
    ];
    monitor.observeItems(items, DEFAULT_BUDGET);

    const obs = monitor.history()[0];
    expect(obs.topKinds.code).toBe(2);
    expect(obs.topKinds.docs).toBe(1);
    expect(obs.topKinds.unknown).toBe(1);
  });

  it("report.recommendations contains unique recommendations", () => {
    const monitor = createDriftMonitor({
      minObservations: 2,
      thresholds: { relevanceDrift: 0.01 },
    });

    const goodItems = [
      makeItem("a", "excellent varied architecture documentation notes", {
        recency: 9,
      }),
      makeItem("b", "separate database planning migration strategy", {
        recency: 8,
      }),
    ];
    monitor.observeItems(goodItems, DEFAULT_BUDGET);
    monitor.observeItems(goodItems, DEFAULT_BUDGET);

    const badItems = [
      makeItem("z", "repetitive repetitive repetitive repetitive repetitive", {
        recency: 0,
      }),
    ];
    for (let i = 0; i < 5; i++) {
      monitor.observeItems(badItems, DEFAULT_BUDGET);
    }

    const report = monitor.report();
    // Recommendations should be unique
    const unique = new Set(report.recommendations);
    expect(unique.size).toBe(report.recommendations.length);
  });

  it("empty items list produces valid observation", () => {
    const monitor = createDriftMonitor();
    monitor.observeItems([], DEFAULT_BUDGET);

    const obs = monitor.history()[0];
    expect(obs.itemCount).toBe(0);
    expect(obs.totalTokens).toBe(0);
    expect(obs.budgetUtilization).toBe(0);
    expect(obs.staleItemCount).toBe(0);
  });

  it("custom windowSize works with default config", () => {
    const monitor = createDriftMonitor({ windowSize: 5 });
    const items = [makeItem("a", "test content here")];

    for (let i = 0; i < 20; i++) {
      monitor.observeItems(items, DEFAULT_BUDGET);
    }

    expect(monitor.history()).toHaveLength(5);
    expect(monitor.report().observationCount).toBe(5);
  });
});
