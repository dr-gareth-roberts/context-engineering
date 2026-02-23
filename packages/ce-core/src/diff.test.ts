import { describe, expect, it } from "vitest";
import { diff } from "./diff";
import type { ContextItem } from "./types";

const before: ContextItem[] = [
  { id: "a", content: "Alpha", tokens: 10 },
  { id: "b", content: "Beta", tokens: 20 }
];

const after: ContextItem[] = [
  { id: "a", content: "Alpha", tokens: 10 },
  { id: "c", content: "Gamma", tokens: 15 }
];

describe("diff", () => {
  it("detects added and removed items", () => {
    const result = diff(before, after);
    expect(result.added.map((item) => item.id)).toEqual(["c"]);
    expect(result.removed.map((item) => item.id)).toEqual(["b"]);
    expect(result.kept.map((item) => item.id)).toEqual(["a"]);
  });
});
