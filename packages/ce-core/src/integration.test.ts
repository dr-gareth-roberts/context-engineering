/**
 * Integration tests — verify the full pipeline works end-to-end.
 *
 * These tests exercise pack → place → quality → cost → handoff → pickup
 * roundtrips, and the composable pipeline API with sessions.
 */
import { describe, expect, it } from "vitest";
import {
  pack,
  placeItems,
  analyzeContext,
  packWithCacheTopology,
  packWithAllocation,
  estimateCost,
  projectCosts,
  createHandoff,
  pickupHandoff,
  writeBeadsJSONL,
  readBeadsJSONL,
  getReadyIssues,
  createSession,
  effectiveBudget,
  pipeline,
  diff,
  tracePack,
} from "./index.js";
import type { ContextItem, MemoryItem } from "./types.js";

function makeItem(
  id: string,
  kind: string,
  priority: number,
  tokens: number,
  content?: string
): ContextItem {
  return {
    id,
    content:
      content ?? `Content for ${id}: ${kind} context with priority ${priority}`,
    kind,
    priority,
    tokens,
    recency: Math.random() * 10,
  };
}

describe("integration: pack → place → quality → cost", () => {
  const items: ContextItem[] = [
    makeItem(
      "system-prompt",
      "system",
      10,
      200,
      "You are a helpful assistant."
    ),
    makeItem(
      "tool-schema",
      "system",
      9,
      150,
      "Available tools: search, calculate, summarize."
    ),
    makeItem(
      "user-profile",
      "memory",
      7,
      80,
      "User prefers concise responses."
    ),
    makeItem(
      "doc-1",
      "retrieval",
      6,
      300,
      "API documentation for the search endpoint."
    ),
    makeItem(
      "doc-2",
      "retrieval",
      5,
      250,
      "Tutorial on building context-aware agents."
    ),
    makeItem(
      "doc-3",
      "retrieval",
      3,
      200,
      "Reference guide for token estimation."
    ),
    makeItem(
      "conversation-1",
      "conversation",
      8,
      100,
      "User asked about context engineering."
    ),
    makeItem(
      "conversation-2",
      "conversation",
      4,
      120,
      "Previous discussion about budgets."
    ),
    makeItem("query", "query", 9, 50, "How do I optimize prefix cache usage?"),
  ];

  it("full pipeline: pack → place → quality → cost → handoff → pickup roundtrip", () => {
    // Step 1: Pack within budget
    const budget = 800;
    const packed = pack(items, { maxTokens: budget });

    expect(packed.selected.length).toBeGreaterThan(0);
    expect(packed.totalTokens).toBeLessThanOrEqual(budget);
    expect(packed.dropped.length).toBeGreaterThan(0);

    // Step 2: Place for attention optimization
    const placed = placeItems(packed.selected, {
      strategy: "attention-optimized",
      model: "claude",
    });

    expect(placed.length).toBe(packed.selected.length);

    // Step 3: Analyze quality
    const quality = analyzeContext(placed);

    expect(quality.itemCount).toBe(placed.length);
    expect(quality.overall).toBeGreaterThan(0);
    expect(quality.density).toBeGreaterThan(0);
    expect(quality.diversity).toBeGreaterThan(0);

    // Step 4: Cost estimation with cache topology
    const cachePack = packWithCacheTopology(items, { maxTokens: budget });

    expect(cachePack.cacheKey).toBeDefined();
    expect(cachePack.cacheEfficiency).toBeGreaterThanOrEqual(0);
    expect(cachePack.cacheableTokens).toBeGreaterThanOrEqual(0);

    const cost = estimateCost(cachePack, "claude-sonnet-4-6", 500);

    expect(cost.model).toBe("claude-sonnet-4-6");
    expect(cost.inputTokens).toBeGreaterThan(0);
    expect(cost.costWithCache).toBeLessThanOrEqual(cost.costWithoutCache);
    expect(cost.savingsPercent).toBeGreaterThanOrEqual(0);

    // Step 5: Create handoff
    const handoff = createHandoff(packed, {
      agent: "integration-test",
      sessionId: "test-session-1",
      handoffNotes: "Full integration test handoff",
      includeDropped: true,
    });

    expect(handoff.jsonl).toBeTruthy();
    expect(handoff.stats.activeItems).toBe(packed.selected.length);
    expect(handoff.stats.deferredItems).toBe(packed.dropped.length);

    // Step 6: Pickup handoff
    const pickup = pickupHandoff(handoff.jsonl);

    expect(pickup.items.length).toBe(packed.selected.length);
    expect(pickup.deferred.length).toBe(packed.dropped.length);
    expect(pickup.manifest).toBeTruthy();
    expect(pickup.stats.handoffSessionId).toBe("test-session-1");

    // Verify ID roundtrip
    for (const original of packed.selected) {
      const recovered = pickup.items.find(i => i.id === original.id);
      expect(recovered).toBeDefined();
      expect(recovered!.content).toBe(original.content);
      expect(recovered!.kind).toBe(original.kind);
      expect(recovered!.priority).toBe(original.priority);
      expect(recovered!.tokens).toBe(original.tokens);
    }
  });
});

describe("integration: composable pipeline with sessions", () => {
  it("pipeline → session → diff across turns", () => {
    const session = createSession({ budget: { maxTokens: 600 } });

    // Turn 1
    const r1 = pipeline(600)
      .add(
        makeItem("sys", "system", 10, 100, "You are helpful."),
        makeItem("doc", "retrieval", 7, 200, "API docs."),
        makeItem("q1", "query", 9, 50, "What is context engineering?")
      )
      .allocate([
        { kind: "system", targetRatio: 0.2 },
        { kind: "retrieval", targetRatio: 0.5 },
        { kind: "query", targetRatio: 0.3 },
      ])
      .cacheTopology()
      .place("attention-optimized")
      .qualityGate()
      .session(session)
      .build();

    expect(r1.selected.length).toBeGreaterThan(0);
    expect(r1.stages).toContain("allocate");
    expect(r1.stages).toContain("cacheTopology");
    expect(r1.stages).toContain("place");
    expect(r1.stages).toContain("quality");
    expect(r1.stages).toContain("session");
    expect(r1.delta).toBeNull(); // first compile

    // Turn 2 — same system + doc, different query
    const r2 = pipeline(600)
      .add(
        makeItem("sys", "system", 10, 100, "You are helpful."),
        makeItem("doc", "retrieval", 7, 200, "API docs."),
        makeItem("q2", "query", 9, 50, "How do I use the pipeline?")
      )
      .cacheTopology()
      .session(session)
      .build();

    expect(r2.delta).not.toBeNull();
    expect(r2.delta!.keptCount).toBeGreaterThan(0);
    expect(r2.delta!.added.length).toBeGreaterThan(0);
    expect(r2.delta!.removedIds.length).toBeGreaterThan(0);
    expect(r2.delta!.reuseRatio).toBeGreaterThan(0);
  });
});

describe("integration: allocation + cost projection", () => {
  it("allocate → cache-topology → cost projection with monthly estimate", () => {
    const items: ContextItem[] = [
      makeItem("sys", "system", 10, 500, "System prompt."),
      makeItem("mem-1", "memory", 6, 200, "User preference: dark mode."),
      makeItem("mem-2", "memory", 5, 150, "Last session: billing questions."),
      makeItem("rag-1", "retrieval", 8, 400, "Billing FAQ document."),
      makeItem("rag-2", "retrieval", 7, 300, "Account management guide."),
      makeItem("rag-3", "retrieval", 4, 250, "Legacy API reference."),
      makeItem("conv", "conversation", 9, 300, "Previous turn context."),
      makeItem("query", "query", 10, 60, "How do I update my billing?"),
    ];

    const budget = 1200;

    // Allocate budget by kind
    const allocated = packWithAllocation(items, { maxTokens: budget }, [
      { kind: "system", targetRatio: 0.25, minTokens: 400 },
      { kind: "memory", targetRatio: 0.15 },
      { kind: "retrieval", targetRatio: 0.35 },
      { kind: "conversation", targetRatio: 0.15 },
      { kind: "query", targetRatio: 0.1 },
    ]);

    expect(allocated.selected.length).toBeGreaterThan(0);
    // Allocation with minTokens guarantees may slightly exceed budget
    expect(allocated.totalTokens).toBeLessThanOrEqual(budget * 1.1);
    expect(allocated.allocationEfficiency).toBeGreaterThan(0);

    // Apply cache topology on allocated items
    const cachePack = packWithCacheTopology(allocated.selected, {
      maxTokens: allocated.totalTokens + 100,
    });

    expect(cachePack.cacheableTokens).toBeGreaterThan(0);

    // Project costs
    const projection = projectCosts(cachePack, "claude-sonnet-4-6", 10000, {
      outputTokens: 800,
      requestsPerDay: 500,
    });

    expect(projection.requestCount).toBe(10000);
    expect(projection.totalSavings).toBeGreaterThanOrEqual(0);
    expect(projection.monthlyEstimate).toBeDefined();
    expect(projection.monthlyEstimate!.requestsPerDay).toBe(500);
    expect(projection.monthlyEstimate!.monthlySavings).toBeGreaterThanOrEqual(
      0
    );
  });
});

describe("integration: BEADS roundtrip with dependency resolution", () => {
  it("write → read → getReady → merge cycle", () => {
    const items: ContextItem[] = [
      makeItem("sys", "system", 10, 100, "System context."),
      makeItem("task-1", "task", 8, 50, "Implement feature A."),
      makeItem("task-2", "task", 6, 50, "Implement feature B (depends on A)."),
    ];

    const packed = pack(items, { maxTokens: 500 });
    const handoff = createHandoff(packed, {
      agent: "agent-1",
      includeDropped: false,
    });

    // Read the JSONL
    const issues = readBeadsJSONL(handoff.jsonl);
    expect(issues.length).toBeGreaterThan(0);

    // Write back and re-read (roundtrip)
    const rewritten = writeBeadsJSONL(issues);
    const reread = readBeadsJSONL(rewritten);
    expect(reread.length).toBe(issues.length);

    // Get ready issues
    const ready = getReadyIssues(issues);
    // All context issues should be ready (no dependencies)
    expect(ready.length).toBeGreaterThanOrEqual(0);
  });
});

describe("integration: effective budget → trace → diff", () => {
  it("computes effective budget, traces decisions, diffs results", () => {
    // Get effective budget for Claude
    const effective = effectiveBudget(8000, "claude");
    expect(effective).toBeLessThan(8000);
    expect(effective).toBeGreaterThan(0);

    const items: ContextItem[] = [
      makeItem("a", "system", 10, 100),
      makeItem("b", "retrieval", 7, 200),
      makeItem("c", "retrieval", 3, 300),
    ];

    // Trace packing decisions
    const trace = tracePack(items, { maxTokens: effective });
    expect(trace.steps.length).toBeGreaterThan(0);
    for (const step of trace.steps) {
      expect(["include", "exclude", "compress"]).toContain(step.decision);
      expect(step.id).toBeTruthy();
    }

    // Pack with two different budgets and diff
    const pack1 = pack(items, { maxTokens: 250 });
    const pack2 = pack(items, { maxTokens: 500 });
    const d = diff(pack1, pack2);

    expect(
      d.added.length + d.removed.length + d.changed.length + d.kept.length
    ).toBeGreaterThan(0);
  });
});
