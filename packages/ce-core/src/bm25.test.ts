import { describe, it, expect } from "vitest";
import { unicodeTokenize } from "./bm25.js";

describe("unicodeTokenize", () => {
  it("tokenizes ASCII text into lowercase words", () => {
    expect(unicodeTokenize("Hello World")).toEqual(["hello", "world"]);
  });

  it("filters tokens with length <= 1", () => {
    expect(unicodeTokenize("I am a dog")).toEqual(["am", "dog"]);
  });

  it("handles Unicode characters", () => {
    const tokens = unicodeTokenize("café résumé naïve");
    expect(tokens).toContain("café");
    expect(tokens).toContain("résumé");
    expect(tokens).toContain("naïve");
  });

  it("handles CJK characters", () => {
    const tokens = unicodeTokenize("hello 世界");
    expect(tokens).toContain("hello");
    expect(tokens).toContain("世界");
    expect(tokens).toHaveLength(2);
  });

  it("returns empty array for empty string", () => {
    expect(unicodeTokenize("")).toEqual([]);
  });

  it("handles mixed alphanumeric", () => {
    const tokens = unicodeTokenize("node16 react19 ts5");
    expect(tokens).toContain("node16");
    expect(tokens).toContain("react19");
    expect(tokens).toContain("ts5");
  });

  it("returns empty array for null/undefined input", () => {
    expect(unicodeTokenize(null as any)).toEqual([]);
    expect(unicodeTokenize(undefined as any)).toEqual([]);
  });
});
