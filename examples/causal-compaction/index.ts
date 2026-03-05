import { createContextManager } from "@context-engineering/core";
import { readBeadsJSONL } from "@context-engineering/core";

/**
 * CAUSAL COMPACTION EXAMPLE
 * 
 * Demonstrates how the toolkit prevents "Agent Drift" by using 
 * the BEADS task graph to prune irrelevant history.
 */

// 1. Define a mock BEADS graph (typically loaded from .beads/issues.jsonl)
const mockBeadsJSONL = `
{"id": "root", "title": "Build a secure Auth system", "status": "open", "issue_type": "epic"}
{"id": "task-a", "title": "Debug CI/CD pipeline", "status": "closed", "issue_type": "task"}
{"id": "task-b", "title": "Implement OAuth2 flow", "status": "open", "issue_type": "task", "dependencies": [{"issue_id": "task-b", "depends_on_id": "root", "type": "parent-child"}]}
`.trim();

const graph = readBeadsJSONL(mockBeadsJSONL);

// 2. Initialize the Context Manager with a tight budget
const ctx = createContextManager({
  budget: { maxTokens: 2000 },
  systemPrompt: "You are a secure coding expert.",
  preserveRecentTurns: 1 // Verbatim keep the very last message
});

ctx.setBeadsGraph(graph);
ctx.setActiveTask("task-b");

console.log("--- Phase 1: Adding History ---");

// Add the Mission Goal
ctx.addTurn({ 
  role: "user", 
  content: "CRITICAL: Build the Auth system using OAuth2. DO NOT use JWT.", 
  taskId: "root" 
} as any);

// Add 10 turns of noise from a task that is now CLOSED
for (let i = 1; i <= 5; i++) {
  ctx.addTurn({ 
    role: "assistant", 
    content: `Fixed CI error #${i} by updating the dockerfile...`, 
    taskId: "task-a" 
  } as any);
}

// Add the active work
ctx.addTurn({ 
  role: "user", 
  content: "I'm starting on the OAuth flow now.", 
  taskId: "task-b" 
} as any);

console.log("\n--- Phase 2: Compiling Context ---");
const result = ctx.compile();

console.log(`\nBudget: 2000 tokens`);
console.log(`Total turns in history: ${ctx.turnCount()}`);
console.log(`Turns kept after causal compaction: ${result.turns.length}`);

console.log("\n--- Active Context Window ---");
result.turns.forEach((turn, i) => {
  console.log(`${i+1}. [${turn.role}] (Task: ${turn.taskId}): ${turn.content.substring(0, 60)}...`);
});

// Observation:
// You will see that the 'root' goal and 'task-b' work are kept, 
// while the 'task-a' (closed) noise has been pruned to stay in budget.
