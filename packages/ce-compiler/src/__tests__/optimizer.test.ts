import { describe, it, expect } from "vitest";
import { optimizeForTarget } from "../optimizer.js";
import type { ContextItem } from "@context-engineering/core";
import type { Slot } from "../types.js";

function item(
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

describe("optimizeForTarget", () => {
  describe("position-aware-placement", () => {
    it("places first-position items at the beginning", () => {
      const items = [
        item("code1", "some code content", { kind: "code" }),
        item("sys1", "system prompt", { kind: "system" }),
      ];
      const slots: Slot[] = [
        { name: "system", kind: "system", position: "first" },
        { name: "code", kind: "code" },
      ];

      const result = optimizeForTarget(items, "generic", slots);
      const firstItem = result.items[0];
      expect(firstItem.kind).toBe("system");
    });

    it("places last-position items at the end", () => {
      const items = [
        item("hist1", "history entry", { kind: "history" }),
        item("code1", "code block", { kind: "code" }),
        item("sys1", "system prompt", { kind: "system" }),
      ];
      const slots: Slot[] = [
        { name: "system", kind: "system", position: "first" },
        { name: "code", kind: "code" },
        { name: "history", kind: "history", position: "last" },
      ];

      const result = optimizeForTarget(items, "generic", slots);
      const lastItem = result.items[result.items.length - 1];
      expect(lastItem.kind).toBe("history");
    });

    it("claude target uses U-shaped priority ordering for any-position items", () => {
      const items = [
        item("a", "item a low priority", { kind: "code", priority: 1 }),
        item("b", "item b high priority", { kind: "code", priority: 10 }),
        item("c", "item c medium priority", { kind: "code", priority: 5 }),
        item("d", "item d very high priority", { kind: "code", priority: 15 }),
      ];
      const slots: Slot[] = [{ name: "code", kind: "code" }];

      const result = optimizeForTarget(items, "claude", slots);
      // High priority items should be at start and end
      const priorities = result.items.map(i => i.priority ?? 0);
      // First item should be highest or second-highest priority
      expect(priorities[0]).toBeGreaterThanOrEqual(priorities[1]);
    });

    it("gpt4 target sorts any-position items by priority descending", () => {
      const items = [
        item("a", "low priority item", { kind: "code", priority: 1 }),
        item("b", "high priority item", { kind: "code", priority: 10 }),
        item("c", "medium priority item", { kind: "code", priority: 5 }),
      ];
      const slots: Slot[] = [{ name: "code", kind: "code" }];

      const result = optimizeForTarget(items, "gpt4", slots);
      const priorities = result.items.map(i => i.priority ?? 0);
      for (let i = 0; i < priorities.length - 1; i++) {
        expect(priorities[i]).toBeGreaterThanOrEqual(priorities[i + 1]);
      }
    });

    it("gemini target groups by kind", () => {
      const items = [
        item("a", "code one", { kind: "code" }),
        item("b", "doc one", { kind: "docs" }),
        item("c", "code two", { kind: "code" }),
      ];
      const slots: Slot[] = [
        { name: "code", kind: "code" },
        { name: "docs", kind: "docs" },
      ];

      const result = optimizeForTarget(items, "gemini", slots);
      // Items should be grouped by kind
      const kinds = result.items.map(i => i.kind);
      const codeIndices = kinds
        .map((k, i) => (k === "code" ? i : -1))
        .filter(i => i >= 0);
      const docsIndices = kinds
        .map((k, i) => (k === "docs" ? i : -1))
        .filter(i => i >= 0);

      // Code items should be contiguous
      if (codeIndices.length > 1) {
        expect(codeIndices[1] - codeIndices[0]).toBe(1);
      }
    });
  });

  describe("cache-prefix-ordering", () => {
    it("sorts first-position items by ID for cache stability", () => {
      const items = [
        item("z-item", "z system content", { kind: "system" }),
        item("a-item", "a system content", { kind: "system" }),
        item("m-item", "m system content", { kind: "system" }),
      ];
      const slots: Slot[] = [
        { name: "system", kind: "system", position: "first" },
      ];

      const result = optimizeForTarget(items, "generic", slots);
      const ids = result.items.map(i => i.id);
      // First-position items should be sorted by ID
      expect(ids).toEqual([...ids].sort());
    });

    it("preserves model-optimized ordering for any-position items", () => {
      const items = [
        item("z-item", "z code content", { kind: "code", priority: 10 }),
        item("a-item", "a code content", { kind: "code", priority: 1 }),
        item("m-item", "m code content", { kind: "code", priority: 5 }),
      ];
      const slots: Slot[] = [{ name: "code", kind: "code" }];

      const result = optimizeForTarget(items, "gpt4", slots);
      const ids = result.items.map(i => i.id);
      // For gpt4, items are sorted by priority descending, not by ID
      expect(ids).not.toEqual([...ids].sort());
    });
  });

  describe("deduplication", () => {
    it("removes items with high Jaccard overlap in deduplicate slots", () => {
      const items = [
        item(
          "a",
          "the quick brown fox jumps over the lazy dog in the park today",
          {
            kind: "code",
          }
        ),
        item(
          "b",
          "the quick brown fox jumps over the lazy dog in the park tonight",
          { kind: "code" }
        ),
        item(
          "c",
          "completely different content about databases and sql queries",
          {
            kind: "code",
          }
        ),
      ];
      const slots: Slot[] = [{ name: "code", kind: "code", deduplicate: true }];

      const result = optimizeForTarget(items, "generic", slots);
      expect(result.items.length).toBeLessThan(3);
      expect(result.passes.find(p => p.name === "deduplication")).toBeDefined();
    });

    it("keeps items in non-deduplicate slots", () => {
      const items = [
        item("a", "the quick brown fox jumps over the lazy dog in the park", {
          kind: "rules",
        }),
        item("b", "the quick brown fox jumps over the lazy dog in the garden", {
          kind: "rules",
        }),
      ];
      const slots: Slot[] = [{ name: "rules", kind: "rules" }];

      const result = optimizeForTarget(items, "generic", slots);
      expect(result.items).toHaveLength(2);
    });
  });

  describe("staleness-pruning", () => {
    it("removes stale items below maxStaleness threshold", () => {
      const items = [
        item("a", "old content from long ago", { kind: "data", recency: 1 }),
        item("b", "fresh content from now", { kind: "data", recency: 8 }),
      ];
      const slots: Slot[] = [{ name: "data", kind: "data", maxStaleness: 5 }];

      const result = optimizeForTarget(items, "generic", slots);
      expect(result.items).toHaveLength(1);
      expect(result.items[0].id).toBe("b");
    });

    it("keeps all items when no maxStaleness is set", () => {
      const items = [
        item("a", "old content", { kind: "data", recency: 1 }),
        item("b", "new content", { kind: "data", recency: 8 }),
      ];
      const slots: Slot[] = [{ name: "data", kind: "data" }];

      const result = optimizeForTarget(items, "generic", slots);
      expect(result.items).toHaveLength(2);
    });
  });

  describe("different targets produce different orderings", () => {
    it("claude and gpt4 produce different item orderings", () => {
      const items = Array.from({ length: 6 }, (_, i) =>
        item(`item-${i}`, `content for item number ${i}`, {
          kind: "code",
          priority: i * 2,
        })
      );
      const slots: Slot[] = [{ name: "code", kind: "code" }];

      const claudeResult = optimizeForTarget(items, "claude", slots);
      const gptResult = optimizeForTarget(items, "gpt4", slots);

      const claudeIds = claudeResult.items.map(i => i.id);
      const gptIds = gptResult.items.map(i => i.id);

      // The orderings should be different because claude uses U-shape
      // while gpt4 uses descending priority
      expect(claudeIds).not.toEqual(gptIds);
    });
  });

  it("returns all four optimization passes", () => {
    const items = [item("a", "content", { kind: "code" })];
    const slots: Slot[] = [{ name: "code", kind: "code" }];

    const result = optimizeForTarget(items, "generic", slots);
    const passNames = result.passes.map(p => p.name);

    expect(passNames).toContain("staleness-pruning");
    expect(passNames).toContain("deduplication");
    expect(passNames).toContain("position-aware-placement");
    expect(passNames).toContain("cache-prefix-ordering");
  });
});
