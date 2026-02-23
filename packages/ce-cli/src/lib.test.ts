import { describe, expect, it } from "vitest";
import { runPack, runDiff, runBudget, lintFile, runTrace } from "./lib";

const items = [
  { id: "x", content: "Alpha", tokens: 10, priority: 2 },
  { id: "y", content: "Beta", tokens: 20, priority: 1 }
];

describe("cli lib", () => {
  it("packs items", () => {
    const pack = runPack(items, 15);
    expect(pack.selected.length).toBe(1);
  });

  it("diffs items", () => {
    const diff = runDiff(items, [{ id: "x", content: "Alpha", tokens: 10 }]);
    expect(diff.removed.length).toBe(1);
  });

  it("estimates budget", () => {
    const tokens = runBudget("hello world");
    expect(tokens).toBeGreaterThan(0);
  });

  it("traces pack decisions", () => {
    const trace = runTrace(items, 15);
    expect(trace.steps.length).toBeGreaterThan(0);
  });

  it("validates schema", async () => {
    const result = await lintFile("context-item", { id: "z", content: "test" });
    expect(result.valid).toBe(true);
  });
});
