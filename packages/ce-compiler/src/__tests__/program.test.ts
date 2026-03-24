import { describe, it, expect } from "vitest";
import { contextProgram } from "../program.js";

describe("contextProgram builder", () => {
  it("creates an empty program", () => {
    const program = contextProgram().build();
    expect(program.slots).toEqual([]);
    expect(program.constraints).toEqual([]);
  });

  it("declares a slot with all options", () => {
    const program = contextProgram()
      .declare("system", {
        kind: "system",
        required: true,
        position: "first",
        maxTokens: 2000,
        minTokens: 100,
        fillRemaining: false,
        strategy: "priority",
        deduplicate: true,
        maxStaleness: 3600,
      })
      .build();

    expect(program.slots).toHaveLength(1);
    expect(program.slots[0]).toEqual({
      name: "system",
      kind: "system",
      required: true,
      position: "first",
      maxTokens: 2000,
      minTokens: 100,
      fillRemaining: false,
      strategy: "priority",
      deduplicate: true,
      maxStaleness: 3600,
    });
  });

  it("declares a minimal slot", () => {
    const program = contextProgram()
      .declare("notes", { kind: "notes" })
      .build();

    expect(program.slots[0]).toEqual({ name: "notes", kind: "notes" });
  });

  it("declares multiple slots", () => {
    const program = contextProgram()
      .declare("system", { kind: "system", required: true, position: "first" })
      .declare("code", { kind: "code", strategy: "relevance" })
      .declare("history", { kind: "history", position: "last" })
      .build();

    expect(program.slots).toHaveLength(3);
    expect(program.slots.map(s => s.name)).toEqual([
      "system",
      "code",
      "history",
    ]);
  });

  it("adds constraints", () => {
    const program = contextProgram()
      .constraint("coverage")
      .constraint("max-redundancy", { threshold: 0.3 })
      .constraint("freshness", { slots: ["history"], threshold: 5 })
      .build();

    expect(program.constraints).toHaveLength(3);
    expect(program.constraints[0]).toEqual({ type: "coverage" });
    expect(program.constraints[1]).toEqual({
      type: "max-redundancy",
      threshold: 0.3,
    });
    expect(program.constraints[2]).toEqual({
      type: "freshness",
      slots: ["history"],
      threshold: 5,
    });
  });

  it("supports fluent chaining", () => {
    const program = contextProgram()
      .declare("a", { kind: "a" })
      .declare("b", { kind: "b" })
      .constraint("coverage")
      .build();

    expect(program.slots).toHaveLength(2);
    expect(program.constraints).toHaveLength(1);
  });

  it("returns a copy of slots and constraints (immutable)", () => {
    const builder = contextProgram().declare("x", { kind: "x" });
    const p1 = builder.build();
    const p2 = builder.build();

    p1.slots.push({
      name: "injected",
      kind: "injected",
    });

    expect(p2.slots).toHaveLength(1);
  });
});
