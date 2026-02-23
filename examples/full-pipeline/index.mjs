/**
 * Full Context Engineering Pipeline Example
 *
 * Demonstrates: memory → bridge → pack → place → analyze → compact
 */
import {
  pack,
  toContextItem,
  placeItems,
  analyzeContext,
  createContextManager,
  createScorer,
  effectiveBudget,
} from "@ce/core";
import { createMemoryStore } from "@ce/memory";

// -- 1. Store and retrieve memories --

const store = createMemoryStore("memory");
await store.put([
  {
    id: "arch",
    content: "The system uses event sourcing with CQRS pattern",
    createdAt: new Date().toISOString(),
    salience: 0.95,
  },
  {
    id: "perf",
    content: "P99 latency must stay under 200ms for all API endpoints",
    createdAt: new Date().toISOString(),
    salience: 0.8,
  },
  {
    id: "style",
    content: "Team prefers functional style with immutability by default",
    createdAt: new Date(Date.now() - 7200000).toISOString(), // 2 hours old
    salience: 0.5,
  },
  {
    id: "old",
    content: "Discussed migrating to Rust but decided against it",
    createdAt: new Date(Date.now() - 86400000).toISOString(), // 1 day old
    salience: 0.2,
  },
]);

const memories = await store.query({ minSalience: 0.3 });
console.log(`Retrieved ${memories.length} memories above salience 0.3\n`);

// -- 2. Bridge memories to context items --

const items = memories.map(m => toContextItem(m, { recencyHalfLife: 3600 }));
console.log("Bridged items:");
items.forEach(i =>
  console.log(`  ${i.id}: recency=${i.recency}, salience=${i.metadata?.salience}`)
);
console.log();

// -- 3. Pack within token budget --

const budget = effectiveBudget(128000, "claude"); // 89600 effective
console.log(`Effective budget for Claude 128K: ${budget} tokens`);

const packed = pack(items, { maxTokens: 50 }); // small budget for demo
console.log(`Packed: ${packed.selected.length} selected, ${packed.dropped.length} dropped`);
console.log();

// -- 4. Position-aware placement --

const placed = placeItems(packed.selected, {
  strategy: "attention-optimized",
  model: "claude",
});
console.log("Placement order (attention-optimized for Claude):");
placed.forEach((item, i) => console.log(`  Position ${i}: ${item.id}`));
console.log();

// -- 5. Quality metrics --

const quality = analyzeContext(packed.selected);
console.log("Context quality:");
console.log(`  Density:    ${quality.density}`);
console.log(`  Diversity:  ${quality.diversity}`);
console.log(`  Redundancy: ${quality.redundancy}`);
console.log(`  Overall:    ${quality.overall}`);
console.log();

// -- 6. Context compaction manager --

const mgr = createContextManager({
  budget: { maxTokens: 200 },
  systemPrompt: "You are a code review assistant.",
  preserveRecentTurns: 2,
  summarizeAfterTurns: 3,
});

mgr.addTurn({ role: "user", content: "Review this pull request for the auth system" });
mgr.addTurn({ role: "assistant", content: "I see several issues with the JWT validation..." });
mgr.addTurn({ role: "user", content: "Can you focus on the token refresh logic?" });
mgr.addTurn({ role: "tool", content: "File: auth/refresh.ts\nfunction refreshToken(token: string) {\n  // ... 50 lines of code\n}" });
mgr.addTurn({ role: "assistant", content: "The refresh logic has a race condition at line 23..." });

const compiled = mgr.compile();
console.log("Compaction manager:");
console.log(`  Total turns: ${mgr.turnCount()}`);
console.log(`  Compiled turns: ${compiled.turns.length}`);
console.log(`  Token usage: ${compiled.totalTokens}/${mgr.getTokenUsage().budget}`);
compiled.turns.forEach((t, i) =>
  console.log(`  Turn ${i}: [${t.role}] ${t.isSummary ? "(summary) " : ""}${t.content.slice(0, 60)}...`)
);
