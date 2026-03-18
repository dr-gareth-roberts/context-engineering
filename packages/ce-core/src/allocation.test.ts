import { describe, expect, it } from "vitest";
import { packWithAllocation, packWithAllocationAsync } from "./allocation.js";
import type { ContextItem } from "./types.js";
import { createContextItem } from "./types.js";

function makeItem(
  id: string,
  kind: string,
  priority: number,
  tokens: number
): ContextItem {
  return { id, content: `content-${id}`, kind, priority, tokens };
}

describe("packWithAllocation", () => {
  it("allocates budget by kind with target ratios", () => {
    const items = [
      makeItem("s1", "system", 10, 50),
      makeItem("r1", "retrieval", 7, 100),
      makeItem("r2", "retrieval", 6, 100),
      makeItem("c1", "conversation", 5, 100),
    ];

    const result = packWithAllocation(items, { maxTokens: 300 }, [
      { kind: "system", targetRatio: 0.2 },
      { kind: "retrieval", targetRatio: 0.5 },
      { kind: "conversation", targetRatio: 0.3 },
    ]);

    expect(result.selected.length).toBeGreaterThan(0);
    expect(result.allocations.system).toBeDefined();
    expect(result.allocations.retrieval).toBeDefined();
    expect(result.allocations.conversation).toBeDefined();
  });

  it("respects minimum token constraints", () => {
    const items = [
      makeItem("s1", "system", 10, 200),
      makeItem("r1", "retrieval", 7, 100),
    ];

    const result = packWithAllocation(items, { maxTokens: 300 }, [
      { kind: "system", minTokens: 200, targetRatio: 0.2 },
      { kind: "retrieval", targetRatio: 0.8 },
    ]);

    // System gets at least 200 even though 0.2 * 300 = 60
    expect(result.allocations.system.budgetAllocated).toBeGreaterThanOrEqual(
      200
    );
  });

  it("respects maximum token constraints", () => {
    const items = [
      makeItem("s1", "system", 10, 50),
      makeItem("r1", "retrieval", 7, 200),
      makeItem("r2", "retrieval", 6, 200),
    ];

    const result = packWithAllocation(items, { maxTokens: 500 }, [
      { kind: "system", targetRatio: 0.5, maxTokens: 100 },
      { kind: "retrieval", targetRatio: 0.5 },
    ]);

    expect(result.allocations.system.budgetUsed).toBeLessThanOrEqual(100);
  });

  it("redistributes surplus by priority", () => {
    const items = [
      makeItem("s1", "system", 10, 30), // only uses 30 of its allocation
      makeItem("r1", "retrieval", 7, 100),
      makeItem("r2", "retrieval", 6, 100),
      makeItem("r3", "retrieval", 5, 100),
    ];

    const result = packWithAllocation(items, { maxTokens: 400 }, [
      { kind: "system", targetRatio: 0.5, priority: 1 },
      { kind: "retrieval", targetRatio: 0.5, priority: 10 },
    ]);

    // Retrieval should get surplus from system's underfill
    expect(result.allocations.retrieval.budgetUsed).toBeGreaterThan(200);
  });

  it("packs uncategorized items into remaining budget", () => {
    const items = [
      makeItem("s1", "system", 10, 50),
      makeItem("misc", "other", 5, 50),
    ];

    const result = packWithAllocation(items, { maxTokens: 200 }, [
      { kind: "system", targetRatio: 0.5 },
    ]);

    // "other" kind is uncategorized, should still be packed
    expect(result.selected.map(i => i.id)).toContain("misc");
    expect(result.allocations._uncategorized).toBeDefined();
  });

  it("reports allocation efficiency", () => {
    const items = [
      makeItem("s1", "system", 10, 100),
      makeItem("r1", "retrieval", 7, 100),
    ];

    const result = packWithAllocation(items, { maxTokens: 200 }, [
      { kind: "system", targetRatio: 0.5 },
      { kind: "retrieval", targetRatio: 0.5 },
    ]);

    // Perfect 50/50 split should yield high efficiency
    expect(result.allocationEfficiency).toBeGreaterThan(0.8);
  });

  it("handles empty items gracefully", () => {
    const result = packWithAllocation([], { maxTokens: 200 }, [
      { kind: "system", targetRatio: 1.0 },
    ]);

    expect(result.selected).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
  });

  it("respects reserve tokens", () => {
    const items = [
      makeItem("s1", "system", 10, 100),
      makeItem("r1", "retrieval", 7, 100),
    ];

    const result = packWithAllocation(
      items,
      { maxTokens: 200, reserveTokens: 50 },
      [
        { kind: "system", targetRatio: 0.5 },
        { kind: "retrieval", targetRatio: 0.5 },
      ]
    );

    expect(result.totalTokens).toBeLessThanOrEqual(150);
  });

  it("never exceeds the total budget when minimums overcommit", () => {
    const items = [
      makeItem("s1", "system", 10, 120),
      makeItem("r1", "retrieval", 9, 120),
    ];

    const result = packWithAllocation(items, { maxTokens: 150 }, [
      { kind: "system", minTokens: 100, priority: 10 },
      { kind: "retrieval", minTokens: 100, priority: 1 },
    ]);

    expect(result.totalTokens).toBeLessThanOrEqual(150);
  });

  it("all items present in selected or dropped", () => {
    const items = [
      makeItem("a", "system", 10, 100),
      makeItem("b", "retrieval", 7, 100),
      makeItem("c", "retrieval", 5, 100),
      makeItem("d", "memory", 3, 100),
    ];

    const result = packWithAllocation(items, { maxTokens: 200 }, [
      { kind: "system", targetRatio: 0.3 },
      { kind: "retrieval", targetRatio: 0.4 },
      { kind: "memory", targetRatio: 0.3 },
    ]);

    const allIds = new Set([
      ...result.selected.map(i => i.id),
      ...result.dropped.map(i => i.id),
    ]);
    expect(allIds.size).toBe(4);
  });
});

describe("packWithAllocationAsync", () => {
  it("produces same structure as sync version", async () => {
    const items = [
      createContextItem("code1", "function hello() {}", {
        kind: "code",
        priority: 8,
      }),
      createContextItem("doc1", "README content", {
        kind: "docs",
        priority: 5,
      }),
    ];
    const budget = { maxTokens: 1000 };
    const allocations = [
      { kind: "code", targetRatio: 0.6 },
      { kind: "docs", targetRatio: 0.4 },
    ];
    const result = await packWithAllocationAsync(items, budget, allocations);
    expect(result.selected).toBeDefined();
    expect(result.dropped).toBeDefined();
    expect(result.totalTokens).toBeGreaterThan(0);
    expect(result.allocations).toBeDefined();
  });

  it("returns same results as sync for identical inputs", async () => {
    const items = [
      makeItem("s1", "system", 10, 50),
      makeItem("r1", "retrieval", 7, 100),
      makeItem("r2", "retrieval", 6, 100),
      makeItem("c1", "conversation", 5, 100),
    ];
    const budget = { maxTokens: 300 };
    const allocations = [
      { kind: "system", targetRatio: 0.2 },
      { kind: "retrieval", targetRatio: 0.5 },
      { kind: "conversation", targetRatio: 0.3 },
    ];

    const syncResult = packWithAllocation(items, budget, allocations);
    const asyncResult = await packWithAllocationAsync(
      items,
      budget,
      allocations
    );

    expect(asyncResult.selected.map(i => i.id)).toEqual(
      syncResult.selected.map(i => i.id)
    );
    expect(asyncResult.totalTokens).toBe(syncResult.totalTokens);
    expect(asyncResult.allocationEfficiency).toBe(
      syncResult.allocationEfficiency
    );
  });

  it("handles empty items gracefully", async () => {
    const result = await packWithAllocationAsync([], { maxTokens: 200 }, [
      { kind: "system", targetRatio: 1.0 },
    ]);

    expect(result.selected).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
  });
});
