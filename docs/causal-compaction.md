# Causal Graph-Aware Compaction

Causal Graph-Aware Compaction is an advanced context management strategy that prevents "Agent Drift" in long-running LLM sessions. It uses the structural relationship between tasks (via the BEADS format) to intelligently prune conversation history while protecting mission-critical goals and outcomes.

## The Problem: Agent Drift & Contextual Alzheimer's

Most LLMs use a **Chronological Sliding Window**. When the token budget is full, the oldest turns are deleted.

This creates a fatal flaw for autonomous agents:
1.  **Phase 1:** The agent receives a high-level goal (e.g., "Build a secure auth system").
2.  **Phase 2:** The agent hits a minor bug (e.g., a linter error) and spends 30 turns debugging it.
3.  **Phase 3:** The chronological window deletes the **Phase 1 Goal** to make room for the **Phase 2 Noise**.
4.  **Result:** The agent fixes the linter but "forgets" why it was building the auth system in the first place, leading to hallucinations or goal abandonment.

## The Solution: Functional Context Value (FCV)

The Context Engineering Toolkit replaces chronological pruning with **Causal Prioritization**. Instead of keeping the most *recent* items, we maximize the **Functional Context Value (FCV)**—the percentage of the window dedicated to:
- **Root Goals:** The "North Star" instructions.
- **The Active Path:** Turns related to the current task.
- **Task Outcomes:** The final results of completed sub-tasks (e.g., a finalized schema) without the debugging noise that produced them.

## How it Works: The Causal Scorer

The `createCausalScorer` builds a multiplier map based on a task graph (typically sourced from a BEADS `.jsonl` file).

| Item Category | Multiplier | Rationale |
|---------------|------------|-----------|
| **Origin / Pinned** | 2.0x | Protects the initial mission and "North Star" constraints. |
| **Active Task** | 2.0x | Ensures the model has all current details for the task at hand. |
| **Outcomes** | 1.5x | Preserves the *result* of previous work (e.g., "The API is at port 80"). |
| **Other Open Tasks**| 1.2x | Keeps context for tasks that are still in progress. |
| **Closed Tasks** | 0.1x | Aggressively prunes the "process noise" (chat logs) of finished tasks. |

## Usage: TypeScript

```ts
import { createContextManager, readBeadsJSONL } from "@context-engineering/core";

const ctx = createContextManager({
  budget: { maxTokens: 8000 },
  preserveRecentTurns: 2 // Always keep the very last few turns verbatim
});

// Load the current task state (BEADS)
const graph = readBeadsJSONL(fs.readFileSync(".beads/issues.jsonl", "utf-8"));
ctx.setBeadsGraph(graph);
ctx.setActiveTask("task-123");

// Add turns tagged with task IDs
ctx.addTurn({ 
  role: "user", 
  content: "Build an auth system", 
  taskId: "root" 
});

// Turns added now will automatically inherit the activeTaskId ("task-123")
ctx.addTurn({ role: "assistant", content: "I am debugging the linter..." });

const compiled = ctx.compile();
// 'compiled.turns' will prioritize 'root' and 'task-123' while dropping 
// closed tasks if the budget is tight.
```

## Usage: Python

```python
from context_engineering import ContextManager, Budget

ctx = ContextManager(
    budget=Budget(maxTokens=8000),
    preserve_recent_turns=2
)

# Set the graph and active task
ctx.set_beads_graph(my_beads_list)
ctx.set_active_task("task-123")

# Add turns
ctx.add_turn("user", "Build an auth system", task_id="root")
ctx.add_turn("assistant", "Implementing OAuth flow...")

result = ctx.compile()
# Maintains mission integrity by pruning irrelevant branches of the task graph.
```

## Implementation Details

- **Automatic Attribution:** If a turn is added without a `taskId`, it inherits the `activeTaskId` currently set on the manager.
- **Outcome Protection:** By marking a turn with `isOutcome: true`, you ensure it stays in the context window even after its parent task is closed and the rest of the task's history is pruned.
- **Graph Distance:** Future versions will support full BFS distance scoring, where items are scored based on their hop-count from the active node in the BEADS dependency graph.
