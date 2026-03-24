import { describe, it, expect, vi } from "vitest";
import { createContextManager } from "./compaction.js";
import type { BeadsIssue } from "./beads.js";

describe("Causal Graph-Aware Compaction", () => {
  it("should prioritize root goal and active task over closed task noise", () => {
    // Custom estimator to make each turn exactly 500 tokens
    const fixedEstimator = () => 500;

    // 1. Setup Manager with a small budget (approx 4 turns)
    const ctx = createContextManager({
      budget: { maxTokens: 2500 },
      systemPrompt: "System",
      tokenEstimator: fixedEstimator,
      preserveRecentTurns: 0,
    });

    // 2. Define the Task Graph
    const graph: BeadsIssue[] = [
      {
        id: "root",
        title: "Mission",
        status: "open",
        priority: 1,
        issue_type: "task",
        created_at: "",
        updated_at: "",
      },
      {
        id: "task-a",
        title: "Old Task",
        status: "closed",
        priority: 3,
        issue_type: "task",
        created_at: "",
        updated_at: "",
      },
      {
        id: "task-b",
        title: "New Task",
        status: "open",
        priority: 2,
        issue_type: "task",
        created_at: "",
        updated_at: "",
      },
    ];

    ctx.setBeadsGraph(graph);
    ctx.setActiveTask("task-b");

    // 3. Add Turns
    // Turn 1: The Root Goal (taskId: root) - 500 tokens
    ctx.addTurn({
      role: "user",
      content: "GOAL: Build a house.",
      taskId: "root",
    } as any);

    // Turns 2-6: Noise from a closed task (taskId: task-a) - 500 tokens each
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({
        role: "assistant",
        content: `Debugging plumbing ${i}...`,
        taskId: "task-a",
      } as any);
    }

    // Turn 7: Active work (taskId: task-b) - 500 tokens
    ctx.addTurn({
      role: "user",
      content: "Now starting on the roof.",
      taskId: "task-b",
    } as any);

    // 4. Compile
    const result = ctx.compile();

    // 5. Verify
    const turnContents = result.turns.map(t => t.content);

    // Should definitely have the Root Goal
    expect(turnContents).toContain("GOAL: Build a house.");

    // Should definitely have the Active Task work
    expect(turnContents).toContain("Now starting on the roof.");

    // Should have dropped most of the "task-a" noise to stay in budget (2500 tokens)
    // Root (500) + Active (500) + System (10) = 1010.
    // Remaining 1490 can fit at most 2 more noise turns.
    expect(result.turns.length).toBeLessThanOrEqual(5);

    // Check that the noise turns that WERE kept are still in chronological order
    const noiseTurns = result.turns.filter(t => t.taskId === "task-a");
    const noiseTimestamps = noiseTurns.map(t => t.timestamp ?? 0);
    const sortedTimestamps = [...noiseTimestamps].sort((a, b) => a - b);
    expect(noiseTimestamps).toEqual(sortedTimestamps);
  });

  it("should protect 'Outcome' turns even if the task is closed", () => {
    // Noise = 500, Outcome = 800
    const customEstimator = (text: string) =>
      text.includes("Outcome") || text.includes("ARCHITECTURE") ? 800 : 500;

    const ctx = createContextManager({
      budget: { maxTokens: 1500 },
      tokenEstimator: customEstimator,
      preserveRecentTurns: 0,
    });

    const graph: BeadsIssue[] = [
      {
        id: "task-a",
        title: "Old Task",
        status: "closed",
        priority: 3,
        issue_type: "task",
        created_at: "",
        updated_at: "",
      },
    ];

    ctx.setBeadsGraph(graph);

    // Add noise (will be pruned)
    ctx.addTurn({
      role: "assistant",
      content: "Noise 1",
      taskId: "task-a",
    } as any);
    ctx.addTurn({
      role: "assistant",
      content: "Noise 2",
      taskId: "task-a",
    } as any);

    // Add an outcome (should be protected)
    // 800 tokens (this + noise would exceed 1500)
    ctx.addTurn({
      role: "assistant",
      content: "FINAL ARCHITECTURE: Blueprint A",
      taskId: "task-a",
      isOutcome: true,
    } as any);

    const result = ctx.compile();
    const turnContents = result.turns.map(t => t.content);

    expect(turnContents).toContain("FINAL ARCHITECTURE: Blueprint A");
    // Since budget is 1500 and Outcome is ~800, it might have room for 1 noise,
    // but the Outcome should definitely be there because its causal multiplier is 1.5x
    // vs noise multiplier 0.1x.
  });
});
