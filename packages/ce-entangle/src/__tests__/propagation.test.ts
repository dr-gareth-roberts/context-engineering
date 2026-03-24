import { describe, it, expect } from "vitest";
import type { EntangledItem } from "../types.js";
import {
  isExpired,
  matchesScope,
  matchesKindFilter,
  filterForAgent,
} from "../propagation.js";

function makeEntangledItem(overrides?: Partial<EntangledItem>): EntangledItem {
  return {
    item: {
      id: overrides?.item?.id ?? "item-1",
      content: "test content",
      kind: overrides?.item?.kind ?? undefined,
      priority: overrides?.item?.priority ?? 5,
    },
    sourceAgent: "agent-a",
    propagation: "next-pack",
    scope: "*",
    entangledAt: 1000,
    ...overrides,
  };
}

describe("isExpired", () => {
  it("returns false when no expiresAt is set", () => {
    const item = makeEntangledItem();
    expect(isExpired(item)).toBe(false);
  });

  it("returns false when current time is before expiresAt", () => {
    const item = makeEntangledItem({ expiresAt: Date.now() + 60_000 });
    expect(isExpired(item)).toBe(false);
  });

  it("returns true when current time is at or past expiresAt", () => {
    const item = makeEntangledItem({ expiresAt: 500 });
    expect(isExpired(item, 500)).toBe(true);
    expect(isExpired(item, 600)).toBe(true);
  });

  it("uses provided now parameter", () => {
    const item = makeEntangledItem({ expiresAt: 2000 });
    expect(isExpired(item, 1999)).toBe(false);
    expect(isExpired(item, 2000)).toBe(true);
  });
});

describe("matchesScope", () => {
  it("returns true for wildcard scope and different agent", () => {
    const item = makeEntangledItem({ scope: "*", sourceAgent: "agent-a" });
    expect(matchesScope(item, "agent-b")).toBe(true);
  });

  it("returns false when agent is the source", () => {
    const item = makeEntangledItem({ scope: "*", sourceAgent: "agent-a" });
    expect(matchesScope(item, "agent-a")).toBe(false);
  });

  it("returns true when agent is in scope list", () => {
    const item = makeEntangledItem({
      scope: ["agent-b", "agent-c"],
      sourceAgent: "agent-a",
    });
    expect(matchesScope(item, "agent-b")).toBe(true);
  });

  it("returns false when agent is not in scope list", () => {
    const item = makeEntangledItem({
      scope: ["agent-b"],
      sourceAgent: "agent-a",
    });
    expect(matchesScope(item, "agent-c")).toBe(false);
  });
});

describe("matchesKindFilter", () => {
  it("returns true when no kind filter is set", () => {
    const item = makeEntangledItem();
    expect(matchesKindFilter(item)).toBe(true);
    expect(matchesKindFilter(item, [])).toBe(true);
  });

  it("returns true when item kind is in the filter", () => {
    const item = makeEntangledItem({
      item: { id: "i", content: "c", kind: "code" },
    });
    expect(matchesKindFilter(item, ["code", "doc"])).toBe(true);
  });

  it("returns false when item kind is not in the filter", () => {
    const item = makeEntangledItem({
      item: { id: "i", content: "c", kind: "code" },
    });
    expect(matchesKindFilter(item, ["doc"])).toBe(false);
  });

  it("returns false when item has no kind but filter is set", () => {
    const item = makeEntangledItem({
      item: { id: "i", content: "c" },
    });
    expect(matchesKindFilter(item, ["code"])).toBe(false);
  });
});

describe("filterForAgent", () => {
  it("excludes expired items", () => {
    const items = [
      makeEntangledItem({ expiresAt: 100 }),
      makeEntangledItem({
        item: { id: "item-2", content: "alive" },
      }),
    ];
    const result = filterForAgent(items, "agent-b", undefined, {
      now: 200,
    });
    expect(result).toHaveLength(1);
    expect(result[0].item.id).toBe("item-2");
  });

  it("excludes items from the same agent (own items)", () => {
    const items = [makeEntangledItem({ sourceAgent: "agent-b" })];
    const result = filterForAgent(items, "agent-b");
    expect(result).toHaveLength(0);
  });

  it("excludes items outside agent scope", () => {
    const items = [makeEntangledItem({ scope: ["agent-c"] })];
    const result = filterForAgent(items, "agent-b");
    expect(result).toHaveLength(0);
  });

  it("excludes on-demand items when forPack is true", () => {
    const items = [makeEntangledItem({ propagation: "on-demand" })];
    const result = filterForAgent(items, "agent-b", undefined, {
      forPack: true,
    });
    expect(result).toHaveLength(0);
  });

  it("includes on-demand items when forPack is false", () => {
    const items = [makeEntangledItem({ propagation: "on-demand" })];
    const result = filterForAgent(items, "agent-b", undefined, {
      forPack: false,
    });
    expect(result).toHaveLength(1);
  });

  it("excludes acknowledged immediate items", () => {
    const items = [makeEntangledItem({ propagation: "immediate" })];
    const acknowledged = new Set(["item-1"]);
    const result = filterForAgent(items, "agent-b", undefined, {
      acknowledged,
    });
    expect(result).toHaveLength(0);
  });

  it("includes unacknowledged immediate items", () => {
    const items = [makeEntangledItem({ propagation: "immediate" })];
    const result = filterForAgent(items, "agent-b");
    expect(result).toHaveLength(1);
  });

  it("applies kind filter", () => {
    const items = [
      makeEntangledItem({
        item: { id: "i1", content: "c", kind: "code" },
      }),
      makeEntangledItem({
        item: { id: "i2", content: "c", kind: "doc" },
      }),
    ];
    const result = filterForAgent(items, "agent-b", ["code"]);
    expect(result).toHaveLength(1);
    expect(result[0].item.id).toBe("i1");
  });
});
