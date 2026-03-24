import { describe, it, expect } from "vitest";
import { validateConstraints } from "../constraints.js";
import type { ContextItem, Budget } from "@context-engineering/core";
import type { Slot, Constraint } from "../types.js";

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

const defaultBudget: Budget = { maxTokens: 10000 };

describe("validateConstraints", () => {
  describe("no-contradiction", () => {
    it("detects contradiction when high overlap with negation mismatch", () => {
      const items = [
        item("a", "you should always use strict mode in typescript projects", {
          kind: "rules",
        }),
        item(
          "b",
          "you should never not use strict mode in typescript projects avoid",
          { kind: "rules" }
        ),
      ];
      const slots: Slot[] = [{ name: "rules", kind: "rules" }];
      const constraints: Constraint[] = [
        { type: "no-contradiction", slots: ["rules"] },
      ];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics.some(d => d.constraint === "no-contradiction")).toBe(
        true
      );
    });

    it("does not flag items with low overlap", () => {
      const items = [
        item("a", "use typescript for all new projects", { kind: "rules" }),
        item("b", "the database should be postgres for production", {
          kind: "rules",
        }),
      ];
      const slots: Slot[] = [{ name: "rules", kind: "rules" }];
      const constraints: Constraint[] = [{ type: "no-contradiction" }];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(
        diagnostics.filter(d => d.constraint === "no-contradiction")
      ).toHaveLength(0);
    });

    it("does not flag items with high overlap but no negation mismatch", () => {
      const items = [
        item("a", "use typescript strict mode always for projects", {
          kind: "rules",
        }),
        item("b", "use typescript strict mode always for projects too", {
          kind: "rules",
        }),
      ];
      const slots: Slot[] = [{ name: "rules", kind: "rules" }];
      const constraints: Constraint[] = [
        { type: "no-contradiction", slots: ["rules"] },
      ];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(
        diagnostics.filter(d => d.constraint === "no-contradiction")
      ).toHaveLength(0);
    });
  });

  describe("freshness", () => {
    it("flags items below recency threshold", () => {
      const items = [
        item("a", "old information", { kind: "data", recency: 2 }),
        item("b", "fresh information", { kind: "data", recency: 8 }),
      ];
      const slots: Slot[] = [{ name: "data", kind: "data" }];
      const constraints: Constraint[] = [
        { type: "freshness", slots: ["data"], threshold: 5 },
      ];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics).toHaveLength(1);
      expect(diagnostics[0].constraint).toBe("freshness");
      expect(diagnostics[0].message).toContain('"a"');
    });

    it("passes when all items are fresh", () => {
      const items = [
        item("a", "fresh data one", { kind: "data", recency: 7 }),
        item("b", "fresh data two", { kind: "data", recency: 9 }),
      ];
      const slots: Slot[] = [{ name: "data", kind: "data" }];
      const constraints: Constraint[] = [
        { type: "freshness", slots: ["data"], threshold: 5 },
      ];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics).toHaveLength(0);
    });
  });

  describe("coverage", () => {
    it("flags missing required slots", () => {
      const items = [item("a", "some code", { kind: "code" })];
      const slots: Slot[] = [
        { name: "system", kind: "system", required: true },
        { name: "code", kind: "code" },
      ];
      const constraints: Constraint[] = [{ type: "coverage" }];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics).toHaveLength(1);
      expect(diagnostics[0].level).toBe("error");
      expect(diagnostics[0].slot).toBe("system");
    });

    it("passes when all required slots are covered", () => {
      const items = [
        item("a", "system prompt", { kind: "system" }),
        item("b", "some code", { kind: "code" }),
      ];
      const slots: Slot[] = [
        { name: "system", kind: "system", required: true },
        { name: "code", kind: "code", required: true },
      ];
      const constraints: Constraint[] = [{ type: "coverage" }];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics).toHaveLength(0);
    });

    it("ignores non-required slots with no items", () => {
      const items = [item("a", "system prompt", { kind: "system" })];
      const slots: Slot[] = [
        { name: "system", kind: "system", required: true },
        { name: "history", kind: "history" },
      ];
      const constraints: Constraint[] = [{ type: "coverage" }];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics).toHaveLength(0);
    });
  });

  describe("budget-utilization", () => {
    it("flags low utilization", () => {
      const items = [item("a", "tiny", { kind: "data", tokens: 100 })];
      const slots: Slot[] = [{ name: "data", kind: "data" }];
      const constraints: Constraint[] = [
        { type: "budget-utilization", threshold: 0.7 },
      ];

      const diagnostics = validateConstraints(items, constraints, slots, {
        maxTokens: 10000,
      });
      expect(diagnostics.some(d => d.constraint === "budget-utilization")).toBe(
        true
      );
    });

    it("passes when utilization is above threshold", () => {
      const items = [item("a", "content", { kind: "data", tokens: 8000 })];
      const slots: Slot[] = [{ name: "data", kind: "data" }];
      const constraints: Constraint[] = [
        { type: "budget-utilization", threshold: 0.7 },
      ];

      const diagnostics = validateConstraints(items, constraints, slots, {
        maxTokens: 10000,
      });
      const budgetDiags = diagnostics.filter(
        d => d.constraint === "budget-utilization" && d.level === "warning"
      );
      expect(budgetDiags).toHaveLength(0);
    });
  });

  describe("max-redundancy", () => {
    it("flags highly overlapping items", () => {
      const items = [
        item("a", "the quick brown fox jumps over the lazy dog today", {
          kind: "data",
        }),
        item("b", "the quick brown fox jumps over the lazy dog tomorrow", {
          kind: "data",
        }),
      ];
      const slots: Slot[] = [{ name: "data", kind: "data" }];
      const constraints: Constraint[] = [
        { type: "max-redundancy", slots: ["data"], threshold: 0.5 },
      ];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(diagnostics.some(d => d.constraint === "max-redundancy")).toBe(
        true
      );
    });

    it("passes when items are distinct", () => {
      const items = [
        item("a", "typescript is a superset of javascript", { kind: "data" }),
        item("b", "postgres handles relational database workloads", {
          kind: "data",
        }),
      ];
      const slots: Slot[] = [{ name: "data", kind: "data" }];
      const constraints: Constraint[] = [
        { type: "max-redundancy", slots: ["data"], threshold: 0.5 },
      ];

      const diagnostics = validateConstraints(
        items,
        constraints,
        slots,
        defaultBudget
      );
      expect(
        diagnostics.filter(d => d.constraint === "max-redundancy")
      ).toHaveLength(0);
    });
  });
});
