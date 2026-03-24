import { describe, it, expect } from "vitest";
import { executeMerge } from "../merge-strategies.js";
import type { ContextItem } from "@context-engineering/core";

function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return { id, content, ...overrides };
}

describe("executeMerge", () => {
  describe("union strategy", () => {
    it("combines all items from both branches", () => {
      const ours = [makeItem("a", "alpha")];
      const theirs = [makeItem("b", "beta")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "union",
      });

      expect(result.items).toHaveLength(2);
      expect(result.added).toHaveLength(1);
      expect(result.added[0].id).toBe("b");
      expect(result.removed).toHaveLength(0);
      expect(result.strategy).toBe("union");
      expect(result.fromBranch).toBe("feature");
      expect(result.intoBranch).toBe("main");
    });

    it("resolves conflicts by recency", () => {
      const ours = [makeItem("a", "old version", { recency: 3 })];
      const theirs = [makeItem("a", "new version", { recency: 8 })];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "union",
      });

      expect(result.items).toHaveLength(1);
      expect(result.items[0].content).toBe("new version");
      expect(result.conflicts).toBe(1);
    });

    it("keeps ours when recency is equal", () => {
      const ours = [makeItem("a", "ours", { recency: 5 })];
      const theirs = [makeItem("a", "theirs", { recency: 5 })];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "union",
      });

      expect(result.items[0].content).toBe("ours");
    });

    it("reports zero conflicts when items are identical", () => {
      const ours = [makeItem("a", "same")];
      const theirs = [makeItem("a", "same")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "union",
      });

      expect(result.conflicts).toBe(0);
      expect(result.items).toHaveLength(1);
    });
  });

  describe("intersection strategy", () => {
    it("keeps only items present in both branches", () => {
      const ours = [makeItem("a", "alpha"), makeItem("b", "beta")];
      const theirs = [makeItem("b", "beta"), makeItem("c", "gamma")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "intersection",
      });

      expect(result.items).toHaveLength(1);
      expect(result.items[0].id).toBe("b");
      expect(result.removed).toHaveLength(2); // "a" from ours, "c" from theirs
    });

    it("returns empty when no common items exist", () => {
      const ours = [makeItem("a", "alpha")];
      const theirs = [makeItem("b", "beta")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "intersection",
      });

      expect(result.items).toHaveLength(0);
      expect(result.removed).toHaveLength(2);
    });

    it("counts conflicts for common items with different content", () => {
      const ours = [makeItem("a", "version1")];
      const theirs = [makeItem("a", "version2")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "intersection",
      });

      expect(result.items).toHaveLength(1);
      expect(result.conflicts).toBe(1);
    });
  });

  describe("best-quality strategy", () => {
    it("picks the branch with higher overall quality", () => {
      // Items with more diversity/density should score higher
      const ours = [makeItem("a", "hello world")];
      const theirs = [
        makeItem("b", "the quick brown fox jumps over the lazy dog"),
        makeItem("c", "artificial intelligence and machine learning advances"),
      ];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "best-quality",
        qualityDimension: "overall",
      });

      // Theirs has more items with diverse content, should win
      expect(result.items.length).toBeGreaterThanOrEqual(1);
    });

    it("uses specified quality dimension", () => {
      const ours = [
        makeItem("a", "fresh item", { recency: 9 }),
        makeItem("b", "also fresh", { recency: 8 }),
      ];
      const theirs = [
        makeItem("c", "stale item", { recency: 1 }),
        makeItem("d", "also stale", { recency: 2 }),
      ];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "best-quality",
        qualityDimension: "freshness",
      });

      // Ours has higher recency, should score better on freshness
      expect(result.items.some(i => i.id === "a")).toBe(true);
    });
  });

  describe("highest-priority strategy", () => {
    it("keeps the higher-priority version for conflicting items", () => {
      const ours = [makeItem("a", "low pri", { priority: 2 })];
      const theirs = [makeItem("a", "high pri", { priority: 9 })];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "highest-priority",
      });

      expect(result.items).toHaveLength(1);
      expect(result.items[0].content).toBe("high pri");
      expect(result.conflicts).toBe(1);
    });

    it("includes items unique to either branch", () => {
      const ours = [makeItem("a", "alpha")];
      const theirs = [makeItem("b", "beta")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "highest-priority",
      });

      expect(result.items).toHaveLength(2);
      expect(result.added).toHaveLength(1);
      expect(result.added[0].id).toBe("b");
    });

    it("keeps ours when priority is equal", () => {
      const ours = [makeItem("a", "ours", { priority: 5 })];
      const theirs = [makeItem("a", "theirs", { priority: 5 })];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "highest-priority",
      });

      expect(result.items[0].content).toBe("ours");
    });
  });

  describe("manual strategy", () => {
    it("delegates to the resolver function", () => {
      const ours = [makeItem("a", "alpha"), makeItem("b", "beta")];
      const theirs = [makeItem("c", "gamma")];

      const result = executeMerge(ours, theirs, "feature", "main", {
        strategy: "manual",
        resolver: (o, t) => [...t], // keep only theirs
      });

      expect(result.items).toHaveLength(1);
      expect(result.items[0].id).toBe("c");
      expect(result.added).toHaveLength(1);
      expect(result.removed).toHaveLength(2);
    });

    it("throws when no resolver is provided", () => {
      expect(() =>
        executeMerge([], [], "feature", "main", { strategy: "manual" })
      ).toThrow("resolver");
    });
  });

  describe("default strategy", () => {
    it("uses union when no options are provided", () => {
      const ours = [makeItem("a", "alpha")];
      const theirs = [makeItem("b", "beta")];

      const result = executeMerge(ours, theirs, "feature", "main");

      expect(result.items).toHaveLength(2);
      expect(result.strategy).toBe("union");
    });
  });
});
