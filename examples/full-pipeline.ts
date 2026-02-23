/**
 * Full Pipeline Example
 *
 * Demonstrates the complete context engineering workflow:
 * 1. Define context items with different kinds
 * 2. Use the composable pipeline to pack, allocate, cache, place, and gate
 * 3. Estimate API costs with prefix caching savings
 * 4. Create a BEADS JSONL handoff for another agent
 * 5. Pick up the handoff and resume
 */

import {
  pipeline,
  estimateCost,
  projectCosts,
  createHandoff,
  pickupHandoff,
  effectiveBudget,
  packWithCacheTopology,
  createSession,
} from "../packages/ce-core/src/index.js";
import type { ContextItem, KindAllocation } from "../packages/ce-core/src/index.js";

// ─── 1. Define Context Items ──────────────────────────────────────────

const systemPrompt: ContextItem = {
  id: "system-prompt",
  content: `You are a senior software engineer helping with a TypeScript monorepo.
Follow clean code practices. Prefer composition over inheritance.
Use strict TypeScript with no 'any' types.`,
  kind: "system",
  priority: 10,
  recency: 1,
  tokens: 45,
};

const toolDefinitions: ContextItem = {
  id: "tools",
  content: `Available tools:
- readFile(path): Read a file from the workspace
- writeFile(path, content): Write a file to the workspace
- runTests(pattern): Run tests matching a pattern
- searchCode(query): Semantic search across the codebase`,
  kind: "tool",
  priority: 9,
  recency: 1,
  tokens: 55,
};

const architectureDocs: ContextItem = {
  id: "architecture",
  content: `The project uses a monorepo with PNPM workspaces.
Packages: ce-core (algorithms), ce-memory (stores), ce-providers (LLM adapters), ce-cli (CLI).
All packages use ESM with Node16 module resolution.
Tests use Vitest. Formatting uses Prettier.`,
  kind: "retrieval",
  priority: 7,
  recency: 5,
  tokens: 60,
};

const recentConversation: ContextItem = {
  id: "conversation-1",
  content: "User: Add a new 'validate' command to the CLI.\nAssistant: I'll add it to cli.ts with input validation.",
  kind: "conversation",
  priority: 6,
  recency: 8,
  tokens: 35,
};

const memoryItem: ContextItem = {
  id: "memory-preference",
  content: "User prefers descriptive variable names and explicit error handling.",
  kind: "memory",
  priority: 5,
  recency: 4,
  tokens: 15,
};

const currentQuery: ContextItem = {
  id: "query",
  content: "Implement the validate command with JSON schema validation using Ajv.",
  kind: "query",
  priority: 8,
  recency: 10,
  tokens: 18,
};

const codeSnippet: ContextItem = {
  id: "code-context",
  content: `// packages/ce-cli/src/cli.ts (relevant section)
program.command("lint").description("Validate data against a JSON schema")
  .requiredOption("-s, --schema <name>", "Schema name")
  .requiredOption("-i, --input <file>", "Path to JSON/JSONL")
  .action(async options => { /* ... */ });`,
  kind: "retrieval",
  priority: 7,
  recency: 9,
  tokens: 50,
};

const items = [
  systemPrompt,
  toolDefinitions,
  architectureDocs,
  recentConversation,
  memoryItem,
  currentQuery,
  codeSnippet,
];

// ─── 2. Calculate Effective Budget ────────────────────────────────────

const advertisedWindow = 200_000; // Claude's 200K context
const budget = effectiveBudget(advertisedWindow, "claude");
console.log(`Advertised: ${advertisedWindow.toLocaleString()} tokens`);
console.log(`Effective:  ${budget.toLocaleString()} tokens (70% for claude)\n`);

// ─── 3. Composable Pipeline ──────────────────────────────────────────

const allocations: KindAllocation[] = [
  { kind: "system", targetRatio: 0.2 },
  { kind: "tool", targetRatio: 0.15 },
  { kind: "retrieval", targetRatio: 0.3 },
  { kind: "conversation", targetRatio: 0.15 },
  { kind: "memory", targetRatio: 0.1 },
  { kind: "query", targetRatio: 0.1 },
];

const session = createSession({ budget: { maxTokens: budget } });

const result = pipeline(budget)
  .add(...items)
  .allocate(allocations)
  .cacheTopology({ provider: "anthropic" })
  .place("attention-optimized")
  .qualityGate({ minOverall: 0.3 })
  .session(session)
  .build();

console.log("=== Pipeline Result ===");
console.log(`Selected: ${result.selected.length}/${items.length} items`);
console.log(`Tokens:   ${result.totalTokens} / ${budget}`);
console.log(`Stages:   ${result.stages.join(" → ")}`);

if (result.quality) {
  console.log(`\nQuality:`);
  console.log(`  Density:    ${result.quality.density}`);
  console.log(`  Diversity:  ${result.quality.diversity}`);
  console.log(`  Freshness:  ${result.quality.freshness}`);
  console.log(`  Redundancy: ${result.quality.redundancy}`);
  console.log(`  Overall:    ${result.quality.overall}`);
}

if (result.cacheKey) {
  console.log(`\nCache topology:`);
  console.log(`  Cache key:    ${result.cacheKey}`);
  console.log(`  Efficiency:   ${(result.cacheEfficiency! * 100).toFixed(1)}%`);
}

console.log(`\nPlacement order:`);
result.selected.forEach((item, i) => {
  console.log(`  ${i + 1}. ${item.id} [${item.kind}] (score: ${item.score?.toFixed(1)})`);
});

// ─── 4. Cost Estimation ──────────────────────────────────────────────

const cachePack = packWithCacheTopology(items, { maxTokens: budget });
const cost = estimateCost(cachePack, "claude-sonnet-4-6");

console.log(`\n=== Cost Estimate (claude-sonnet-4-6) ===`);
console.log(`Per request:`);
console.log(`  Without cache: $${cost.costWithoutCache.toFixed(6)}`);
console.log(`  With cache:    $${cost.costWithCache.toFixed(6)}`);
console.log(`  Savings:       $${cost.savings.toFixed(6)} (${cost.savingsPercent}%)`);

const projection = projectCosts(cachePack, "claude-sonnet-4-6", 10000, {
  requestsPerDay: 1000,
});

if (projection.monthlyEstimate) {
  console.log(`\nMonthly (1000 req/day):`);
  console.log(`  Without cache: $${projection.monthlyEstimate.monthlyCostWithoutCache.toFixed(2)}/mo`);
  console.log(`  With cache:    $${projection.monthlyEstimate.monthlyCostWithCache.toFixed(2)}/mo`);
  console.log(`  Savings:       $${projection.monthlyEstimate.monthlySavings.toFixed(2)}/mo`);
}

// ─── 5. Agent Handoff (BEADS) ─────────────────────────────────────────

const handoff = createHandoff(result, {
  agent: "engineer-agent-1",
  sessionId: "session-abc123",
  includeDropped: true,
  handoffNotes: "Working on adding validate CLI command. Schema validation with Ajv is the approach.",
});

console.log(`\n=== BEADS Handoff ===`);
console.log(`Issues:   ${handoff.stats.totalIssues}`);
console.log(`Active:   ${handoff.stats.activeItems}`);
console.log(`Deferred: ${handoff.stats.deferredItems}`);
console.log(`JSONL size: ${handoff.jsonl.length} bytes`);

// ─── 6. Pickup (simulating another agent) ─────────────────────────────

const pickup = pickupHandoff(handoff.jsonl);

console.log(`\n=== Pickup (Agent 2) ===`);
console.log(`Recovered: ${pickup.stats.contextItems} context items`);
console.log(`Deferred:  ${pickup.stats.deferredItems} deferred items`);
console.log(`Session:   ${pickup.stats.handoffSessionId}`);

// Agent 2 can now resume with full context
const session2 = createSession({ budget: { maxTokens: budget } });
const result2 = pipeline(budget)
  .add(...pickup.items)
  .cacheTopology({ provider: "anthropic" })
  .session(session2)
  .build();

console.log(`\nAgent 2 context: ${result2.selected.length} items, ${result2.totalTokens} tokens`);
console.log("Handoff complete — Agent 2 has full context.");
