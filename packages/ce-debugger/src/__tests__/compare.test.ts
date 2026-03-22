import { describe, it, expect } from "vitest";
import { compareResponses } from "../compare.js";
import type { ContextPack, ContextItem } from "@context-engineering/core";

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

describe("compareResponses", () => {
  it("identifies items unique to each pack", () => {
    const packA = makePack({
      selected: [
        makeItem({ id: "shared", content: "shared content" }),
        makeItem({ id: "only-a", content: "only in pack a" }),
      ],
      totalTokens: 20,
    });

    const packB = makePack({
      selected: [
        makeItem({ id: "shared", content: "shared content" }),
        makeItem({ id: "only-b", content: "only in pack b" }),
      ],
      totalTokens: 20,
    });

    const result = compareResponses(packA, 0.7, packB, 0.8);

    expect(result.itemDiff.onlyInA).toEqual(["only-a"]);
    expect(result.itemDiff.onlyInB).toEqual(["only-b"]);
    expect(result.itemDiff.shared).toEqual(["shared"]);
  });

  it("computes quality delta correctly (positive when B is better)", () => {
    const packA = makePack({
      selected: [makeItem({ id: "a", content: "a" })],
      totalTokens: 10,
    });
    const packB = makePack({
      selected: [makeItem({ id: "b", content: "b" })],
      totalTokens: 10,
    });

    const result = compareResponses(packA, 0.5, packB, 0.9);

    expect(result.qualityDelta).toBeCloseTo(0.4);
  });

  it("generates insight about additional items correlating with better quality", () => {
    const packA = makePack({
      selected: [makeItem({ id: "a", content: "content a" })],
      totalTokens: 10,
    });
    const packB = makePack({
      selected: [
        makeItem({ id: "a", content: "content a" }),
        makeItem({ id: "b", content: "content b extra" }),
      ],
      totalTokens: 20,
    });

    const result = compareResponses(packA, 0.5, packB, 0.8);

    const additionalInsight = result.insights.find(i =>
      i.includes("additional item")
    );
    expect(additionalInsight).toBeDefined();
  });

  it("handles identical packs (all items shared)", () => {
    const items = [
      makeItem({ id: "x", content: "shared item x" }),
      makeItem({ id: "y", content: "shared item y" }),
    ];

    const packA = makePack({ selected: items, totalTokens: 20 });
    const packB = makePack({ selected: items, totalTokens: 20 });

    const result = compareResponses(packA, 0.7, packB, 0.7);

    expect(result.itemDiff.onlyInA).toHaveLength(0);
    expect(result.itemDiff.onlyInB).toHaveLength(0);
    expect(result.itemDiff.shared).toHaveLength(2);
    expect(result.qualityDelta).toBeCloseTo(0);

    const identicalInsight = result.insights.find(i => i.includes("identical"));
    expect(identicalInsight).toBeDefined();
  });

  it("handles completely different packs (no shared items)", () => {
    const packA = makePack({
      selected: [
        makeItem({ id: "a1", content: "alpha content" }),
        makeItem({ id: "a2", content: "beta content" }),
      ],
      totalTokens: 20,
    });
    const packB = makePack({
      selected: [
        makeItem({ id: "b1", content: "gamma content" }),
        makeItem({ id: "b2", content: "delta content" }),
      ],
      totalTokens: 20,
    });

    const result = compareResponses(packA, 0.6, packB, 0.8);

    expect(result.itemDiff.shared).toHaveLength(0);
    expect(result.itemDiff.onlyInA).toHaveLength(2);
    expect(result.itemDiff.onlyInB).toHaveLength(2);

    const noSharedInsight = result.insights.find(i => i.includes("no items"));
    expect(noSharedInsight).toBeDefined();
  });
});
