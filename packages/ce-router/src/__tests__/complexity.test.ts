import { describe, it, expect } from "vitest";
import { analyzeComplexity } from "../complexity.js";
import type { ContextItem } from "@context-engineering/core";

function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return { id, content, ...overrides };
}

describe("analyzeComplexity", () => {
  it("returns zero complexity for empty items array", () => {
    const result = analyzeComplexity([]);
    expect(result.overall).toBe(0);
    expect(result.dimensions.diversity).toBe(0);
    expect(result.dimensions.density).toBe(0);
    expect(result.dimensions.dependencyDepth).toBe(0);
    expect(result.dimensions.toolCallCount).toBe(0);
    expect(result.dimensions.multilinguality).toBe(0);
    expect(result.dimensions.averageItemLength).toBe(0);
  });

  it("produces low complexity for simple short items", () => {
    const items = [makeItem("a", "hello world"), makeItem("b", "simple test")];
    const result = analyzeComplexity(items);
    expect(result.overall).toBeGreaterThanOrEqual(0);
    expect(result.overall).toBeLessThan(0.5);
  });

  it("produces high dependencyDepth for deep dependsOn chains", () => {
    const items = [
      makeItem("a", "root item"),
      makeItem("b", "depends on a", { dependsOn: ["a"] }),
      makeItem("c", "depends on b", { dependsOn: ["b"] }),
      makeItem("d", "depends on c", { dependsOn: ["c"] }),
      makeItem("e", "depends on d", { dependsOn: ["d"] }),
      makeItem("f", "depends on e", { dependsOn: ["e"] }),
    ];
    const result = analyzeComplexity(items);
    // Chain depth is 5 (f -> e -> d -> c -> b -> a), normalized by 10 = 0.5
    expect(result.dimensions.dependencyDepth).toBe(0.5);
  });

  it("increases toolCallCount for items with tool-related kinds", () => {
    const items = [
      makeItem("a", "regular item", { kind: "text" }),
      makeItem("b", "tool usage", { kind: "tool_call" }),
      makeItem("c", "another tool", { kind: "TOOL_RESULT" }),
      makeItem("d", "plain content", { kind: "code" }),
    ];
    const result = analyzeComplexity(items);
    // 2 out of 4 items have 'tool' in kind = 0.5
    expect(result.dimensions.toolCallCount).toBe(0.5);
  });

  it("increases multilinguality for mixed-language content", () => {
    const items = [
      makeItem("a", "Hello world in English"),
      makeItem("b", "Bonjour le monde"),
      makeItem("c", "\u4F60\u597D\u4E16\u754C"), // Chinese
      makeItem("d", "\u041F\u0440\u0438\u0432\u0435\u0442 \u043C\u0438\u0440"), // Russian (Cyrillic)
    ];
    const result = analyzeComplexity(items);
    // Latin + CJK + Cyrillic = 3 scripts, (3-1)/4 = 0.5
    expect(result.dimensions.multilinguality).toBeGreaterThan(0);
  });

  it("increases averageItemLength for long items", () => {
    const longContent = "word ".repeat(3000); // ~3000 words, ~3900 tokens
    const items = [makeItem("a", longContent), makeItem("b", longContent)];
    const result = analyzeComplexity(items);
    // Mean tokens ~3900, normalized by 2000 = ~1.95, clamped to 1.0
    expect(result.dimensions.averageItemLength).toBe(1);
  });

  it("uses custom weights to influence overall score", () => {
    const items = [makeItem("a", "tool usage", { kind: "tool_call" })];

    // With default weights
    const defaultResult = analyzeComplexity(items);

    // With toolCallCount weight boosted to dominate
    const boostedResult = analyzeComplexity(items, {
      toolCallCount: 10,
      diversity: 0,
      density: 0,
      dependencyDepth: 0,
      multilinguality: 0,
      averageItemLength: 0,
    });

    // The boosted result should have toolCallCount dominate the overall score
    expect(boostedResult.overall).toBeGreaterThan(defaultResult.overall);
    // With only toolCallCount at weight 10 and tool item, overall should equal toolCallCount
    expect(boostedResult.overall).toBe(boostedResult.dimensions.toolCallCount);
  });

  it("handles single-script content with zero multilinguality", () => {
    const items = [
      makeItem("a", "Only English content here"),
      makeItem("b", "More English words to process"),
    ];
    const result = analyzeComplexity(items);
    // 1 script (Latin), (1-1)/4 = 0
    expect(result.dimensions.multilinguality).toBe(0);
  });
});
