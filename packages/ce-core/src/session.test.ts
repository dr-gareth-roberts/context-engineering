import { describe, expect, it } from "vitest";
import { createSession } from "./session.js";
import type { ContextItem } from "./types.js";

function makeItem(id: string, priority: number, tokens: number): ContextItem {
  return { id, content: `content-${id}`, priority, tokens };
}

describe("createSession", () => {
  it("compiles items into a pack", () => {
    const session = createSession({ budget: { maxTokens: 500 } });
    session.setItems([makeItem("a", 10, 50), makeItem("b", 5, 50)]);

    const result = session.compile();
    expect(result.selected).toHaveLength(2);
    expect(result.totalTokens).toBe(100);
    expect(result.compileCount).toBe(1);
  });

  it("returns null delta on first compile", () => {
    const session = createSession({ budget: { maxTokens: 500 } });
    session.setItems([makeItem("a", 10, 50)]);
    const result = session.compile();
    expect(result.delta).toBeNull();
  });

  it("computes delta on subsequent compiles", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([makeItem("a", 10, 50), makeItem("b", 5, 50)]);
    session.compile();

    // Same items — everything reused
    const r2 = session.compile();
    expect(r2.delta).not.toBeNull();
    expect(r2.delta!.added).toHaveLength(0);
    expect(r2.delta!.removedIds).toHaveLength(0);
    expect(r2.delta!.keptCount).toBe(2);
    expect(r2.delta!.reuseRatio).toBe(1);
  });

  it("detects added items", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([makeItem("a", 10, 50)]);
    session.compile();

    session.addItems([makeItem("b", 5, 50)]);
    const r2 = session.compile();

    expect(r2.delta!.added).toHaveLength(1);
    expect(r2.delta!.added[0].id).toBe("b");
    expect(r2.delta!.keptCount).toBe(1);
  });

  it("detects removed items", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([makeItem("a", 10, 50), makeItem("b", 5, 50)]);
    session.compile();

    session.removeItems(["b"]);
    const r2 = session.compile();

    expect(r2.delta!.removedIds).toContain("b");
    expect(r2.delta!.keptCount).toBe(1);
  });

  it("detects changed items", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([
      { id: "a", content: "original content", priority: 10, tokens: 50 },
    ]);
    session.compile();

    session.setItems([
      { id: "a", content: "modified content", priority: 10, tokens: 50 },
    ]);
    const r2 = session.compile();

    expect(r2.delta!.changed).toHaveLength(1);
    expect(r2.delta!.changed[0].id).toBe("a");
    expect(r2.delta!.keptCount).toBe(0);
  });

  it("computes reuse ratio correctly", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([makeItem("a", 10, 100), makeItem("b", 5, 100)]);
    session.compile();

    // Replace b, keep a
    session.setItems([makeItem("a", 10, 100), makeItem("c", 5, 100)]);
    const r2 = session.compile();

    // a (100 tokens) reusable out of 200 total previous
    expect(r2.delta!.reusableTokens).toBe(100);
    expect(r2.delta!.reuseRatio).toBe(0.5);
  });

  it("treats reordered items as non-reusable prefix", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([makeItem("a", 10, 100), makeItem("b", 9, 80)]);
    const first = session.compile();

    session.setItems([makeItem("b", 10, 80), makeItem("a", 9, 100)]);
    const second = session.compile();

    expect(second.delta!.keptCount).toBe(2);
    expect(second.delta!.reusableTokens).toBe(0);
    expect(second.delta!.reuseRatio).toBe(0);
    expect(second.cacheKey).toBe(first.cacheKey);
  });

  it("counts only the unchanged leading prefix as reusable", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([
      { id: "a", content: "stable", priority: 10, tokens: 100 },
      { id: "b", content: "old", priority: 9, tokens: 80 },
      { id: "c", content: "also-stable", priority: 8, tokens: 60 },
    ]);
    session.compile();

    session.setItems([
      { id: "a", content: "stable", priority: 10, tokens: 100 },
      { id: "b", content: "new", priority: 9, tokens: 80 },
      { id: "c", content: "also-stable", priority: 8, tokens: 60 },
    ]);
    const result = session.compile();

    expect(result.delta!.reusableTokens).toBe(100);
    expect(result.delta!.reuseRatio).toBe(0.417);
  });

  it("reports delta tokens", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    session.setItems([makeItem("a", 10, 100)]);
    session.compile();

    session.setItems([makeItem("a", 10, 100), makeItem("b", 5, 50)]);
    const r2 = session.compile();

    expect(r2.delta!.deltaTokens).toBe(50); // only b is new
  });

  it("increments compile count", () => {
    const session = createSession({ budget: { maxTokens: 500 } });
    session.setItems([makeItem("a", 10, 50)]);

    expect(session.getCompileCount()).toBe(0);
    session.compile();
    expect(session.getCompileCount()).toBe(1);
    session.compile();
    expect(session.getCompileCount()).toBe(2);
  });

  it("clear resets session state", () => {
    const session = createSession({ budget: { maxTokens: 500 } });
    session.setItems([makeItem("a", 10, 50)]);
    session.compile();

    session.clear();
    expect(session.itemCount()).toBe(0);
    expect(session.getCompileCount()).toBe(0);

    // After clear, first compile should have null delta
    session.setItems([makeItem("b", 5, 50)]);
    const result = session.compile();
    expect(result.delta).toBeNull();
  });

  it("addItems deduplicates by id", () => {
    const session = createSession({ budget: { maxTokens: 500 } });
    session.setItems([makeItem("a", 10, 50)]);
    session.addItems([makeItem("a", 8, 60)]); // override a
    expect(session.itemCount()).toBe(1);
  });

  it("respects budget when packing", () => {
    const session = createSession({ budget: { maxTokens: 100 } });
    session.setItems([makeItem("a", 10, 60), makeItem("b", 5, 60)]);

    const result = session.compile();
    expect(result.totalTokens).toBeLessThanOrEqual(100);
    expect(result.dropped.length).toBeGreaterThan(0);
  });

  it("multiple rounds maintain correct deltas", () => {
    const session = createSession({ budget: { maxTokens: 500 } });

    // Round 1
    session.setItems([makeItem("a", 10, 50)]);
    session.compile();

    // Round 2: add b
    session.addItems([makeItem("b", 5, 50)]);
    const r2 = session.compile();
    expect(r2.delta!.added).toHaveLength(1);
    expect(r2.delta!.keptCount).toBe(1);

    // Round 3: remove a, add c
    session.removeItems(["a"]);
    session.addItems([makeItem("c", 3, 50)]);
    const r3 = session.compile();
    expect(r3.delta!.added).toHaveLength(1);
    expect(r3.delta!.removedIds).toContain("a");
    expect(r3.delta!.keptCount).toBe(1); // b kept
  });

  it("compile() with custom weights changes item selection order", () => {
    const session = createSession({ budget: { maxTokens: 80 } });

    // Two items that don't both fit. 'a' has higher priority, 'b' has higher recency.
    const a: ContextItem = {
      id: "a",
      content: "item-a",
      priority: 10,
      recency: 1,
      tokens: 50,
    };
    const b: ContextItem = {
      id: "b",
      content: "item-b",
      priority: 1,
      recency: 10,
      tokens: 50,
    };

    // With priority-heavy weights, 'a' should be selected
    session.setItems([a, b]);
    const r1 = session.compile({ weights: { priority: 1.0, recency: 0.0 } });
    expect(r1.selected[0].id).toBe("a");

    session.clear();

    // With recency-heavy weights, 'b' should be selected
    session.setItems([a, b]);
    const r2 = session.compile({ weights: { priority: 0.0, recency: 1.0 } });
    expect(r2.selected[0].id).toBe("b");
  });

  it("compile() with custom tokenEstimator is used", () => {
    // Custom estimator that always returns 1 token per item
    const tinyEstimator = (_content: string) => 1;

    const session = createSession({
      budget: { maxTokens: 10 },
      packOptions: { tokenEstimator: tinyEstimator },
    });

    // Without custom estimator, these items would be ~13 tokens each
    // and wouldn't all fit in budget 10.
    // With our custom estimator (1 token each), all 5 should fit.
    const items: ContextItem[] = Array.from({ length: 5 }, (_, i) => ({
      id: `item-${i}`,
      content: `This is some longer content for item number ${i}`,
      priority: 5,
    }));

    session.setItems(items);
    const result = session.compile();
    expect(result.selected).toHaveLength(5);
  });

  it("compile() options override session defaultPackOptions", () => {
    // Session created with priority-heavy default weights
    const session = createSession({
      budget: { maxTokens: 80 },
      packOptions: { weights: { priority: 1.0, recency: 0.0 } },
    });

    const a: ContextItem = {
      id: "a",
      content: "item-a",
      priority: 10,
      recency: 1,
      tokens: 50,
    };
    const b: ContextItem = {
      id: "b",
      content: "item-b",
      priority: 1,
      recency: 10,
      tokens: 50,
    };

    // Default weights should favor 'a' (high priority)
    session.setItems([a, b]);
    const r1 = session.compile();
    expect(r1.selected[0].id).toBe("a");

    session.clear();

    // Override with recency-heavy weights should favor 'b'
    session.setItems([a, b]);
    const r2 = session.compile({ weights: { priority: 0.0, recency: 1.0 } });
    expect(r2.selected[0].id).toBe("b");
  });
});
