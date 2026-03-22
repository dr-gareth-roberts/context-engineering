import { describe, it, expect } from "vitest";
import { replay } from "./replay.js";
import { createContextRecorder } from "./recorder.js";
import { pack } from "./pack.js";
import type { ContextItem, Budget } from "./types.js";

function makeItems(): ContextItem[] {
  return [
    {
      id: "system",
      content: "System prompt",
      priority: 10,
      recency: 5,
      tokens: 10,
    },
    {
      id: "code",
      content: "function foo() { return 42; }",
      priority: 8,
      recency: 8,
      tokens: 20,
    },
    {
      id: "docs",
      content: "API documentation for the foo module",
      priority: 4,
      recency: 2,
      tokens: 25,
    },
    {
      id: "chat",
      content: "User asked about testing",
      priority: 6,
      recency: 9,
      tokens: 15,
    },
  ];
}

function createRecordingsForReplay() {
  const recorder = createContextRecorder();
  const items = makeItems();

  // Record with a tight budget (not everything fits)
  const budget: Budget = { maxTokens: 50 };
  const result = pack(items, budget);

  recorder.record({
    model: "gpt-4o",
    items,
    budget,
    result,
  });

  return { recorder, items, budget };
}

describe("replay", () => {
  it("replays recordings with baseline variant (same options)", () => {
    const { recorder } = createRecordingsForReplay();

    const report = replay(recorder.getRecordings(), [{ name: "baseline" }]);

    expect(report.recordingCount).toBe(1);
    expect(report.variants).toHaveLength(1);
    expect(report.variants[0].name).toBe("baseline");
    expect(report.variants[0].results).toHaveLength(1);
    // Same options = same result = zero delta
    expect(report.variants[0].avgTokenDelta).toBe(0);
  });

  it("replays with a different budget", () => {
    const { recorder } = createRecordingsForReplay();

    const report = replay(recorder.getRecordings(), [
      { name: "tight", budget: { maxTokens: 30 } },
      { name: "loose", budget: { maxTokens: 200 } },
    ]);

    expect(report.variants).toHaveLength(2);

    const tight = report.variants.find(v => v.name === "tight")!;
    const loose = report.variants.find(v => v.name === "loose")!;

    // Tight budget should use fewer or equal tokens
    expect(tight.results[0].pack.totalTokens).toBeLessThanOrEqual(30);

    // Loose budget should include everything
    expect(loose.results[0].pack.selected.length).toBe(4);
    expect(loose.results[0].pack.dropped.length).toBe(0);
  });

  it("reports selection changes between original and variant", () => {
    const { recorder } = createRecordingsForReplay();

    const report = replay(recorder.getRecordings(), [
      { name: "loose", budget: { maxTokens: 200 } },
    ]);

    const result = report.variants[0].results[0];
    // With a loose budget, items that were dropped originally should now be selected
    expect(result.selectionChanges.newlySelected.length).toBeGreaterThan(0);
    expect(result.selectionChanges.newlyDropped).toHaveLength(0);
  });

  it("replays with different scoring weights", () => {
    const { recorder } = createRecordingsForReplay();

    const report = replay(recorder.getRecordings(), [
      {
        name: "recency-heavy",
        options: { weights: { priority: 0.1, recency: 5.0 } },
      },
      {
        name: "priority-heavy",
        options: { weights: { priority: 5.0, recency: 0.1 } },
      },
    ]);

    const recencyHeavy = report.variants.find(v => v.name === "recency-heavy")!;
    const priorityHeavy = report.variants.find(
      v => v.name === "priority-heavy"
    )!;

    // Different weights should potentially produce different selections
    expect(recencyHeavy.results).toHaveLength(1);
    expect(priorityHeavy.results).toHaveLength(1);
  });

  it("calculates average utilization across recordings", () => {
    const recorder = createContextRecorder();
    const items = makeItems();

    // Create two recordings
    const budget1: Budget = { maxTokens: 50 };
    const budget2: Budget = { maxTokens: 100 };
    recorder.record({
      model: "gpt-4o",
      items,
      budget: budget1,
      result: pack(items, budget1),
    });
    recorder.record({
      model: "gpt-4o",
      items,
      budget: budget2,
      result: pack(items, budget2),
    });

    const report = replay(recorder.getRecordings(), [{ name: "baseline" }]);

    expect(report.recordingCount).toBe(2);
    expect(report.variants[0].avgUtilization).toBeGreaterThan(0);
    expect(report.variants[0].avgUtilization).toBeLessThanOrEqual(100);
  });

  it("handles empty recordings gracefully", () => {
    const report = replay([], [{ name: "baseline" }]);
    expect(report.recordingCount).toBe(0);
    expect(report.variants[0].results).toHaveLength(0);
    expect(report.variants[0].avgTokenDelta).toBe(0);
  });

  it("counts affected recordings correctly", () => {
    const { recorder } = createRecordingsForReplay();

    const report = replay(recorder.getRecordings(), [
      { name: "baseline" },
      { name: "loose", budget: { maxTokens: 200 } },
    ]);

    const baseline = report.variants.find(v => v.name === "baseline")!;
    const loose = report.variants.find(v => v.name === "loose")!;

    // Baseline should not affect any recordings (same options)
    expect(baseline.recordingsAffected).toBe(0);
    // Loose budget should affect the recording (different selection)
    expect(loose.recordingsAffected).toBe(1);
  });
});
