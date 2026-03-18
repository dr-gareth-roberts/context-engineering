import { describe, expect, it } from "vitest";
import {
  openaiTokenEstimator,
  anthropicTokenEstimator,
} from "./token-estimators.js";

describe("openaiTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = openaiTokenEstimator("Hello, world!");
    expect(tokens).toBeGreaterThan(0);
    expect(tokens).toBeLessThan(20);
  });

  it("returns 0 for empty string", () => {
    expect(openaiTokenEstimator("")).toBe(0);
  });

  it("returns 0 for null/undefined input", () => {
    expect(openaiTokenEstimator(null as unknown as string)).toBe(0);
    expect(openaiTokenEstimator(undefined as unknown as string)).toBe(0);
  });

  it("handles long text", () => {
    const long = "word ".repeat(1000);
    const tokens = openaiTokenEstimator(long);
    expect(tokens).toBeGreaterThan(500);
  });

  it("is consistent across calls (cached encoding)", () => {
    const first = openaiTokenEstimator("test string");
    const second = openaiTokenEstimator("test string");
    expect(first).toBe(second);
  });

  it("uses o200k_base by default for modern models", () => {
    // o200k_base and cl100k_base produce different counts for the same text
    const defaultCount = openaiTokenEstimator("Hello, world!");
    const withGpt4o = openaiTokenEstimator("Hello, world!", {
      model: "gpt-4o",
    });
    // Both should use o200k_base, so same result
    expect(defaultCount).toBe(withGpt4o);
  });

  it("uses cl100k_base for older models when specified", () => {
    // CJK + emoji text reliably produces different token counts between cl100k and o200k
    const text = "こんにちは世界 🎉🎊🎈🎁🎀🎇🎆✨ Hello World";
    const modern = openaiTokenEstimator(text);
    const legacy = openaiTokenEstimator(text, {
      model: "gpt-3.5-turbo",
    });
    expect(modern).toBeGreaterThan(0);
    expect(legacy).toBeGreaterThan(0);
    // The two encodings must produce different tokenizations
    expect(modern).not.toBe(legacy);
  });

  it("accepts options parameter without model", () => {
    const tokens = openaiTokenEstimator("Hello", {});
    expect(tokens).toBeGreaterThan(0);
  });

  it("handles unicode and emoji input", () => {
    expect(openaiTokenEstimator("\u{1F389}\u{1F389}\u{1F389}")).toBeGreaterThan(
      0
    );
    expect(openaiTokenEstimator("\u4F60\u597D\u4E16\u754C")).toBeGreaterThan(0);
  });
});

describe("anthropicTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = anthropicTokenEstimator("Hello, world!");
    expect(tokens).toBeGreaterThan(0);
  });

  it("returns 0 for empty string", () => {
    expect(anthropicTokenEstimator("")).toBe(0);
  });

  it("returns 0 for null/undefined input", () => {
    expect(anthropicTokenEstimator(null as unknown as string)).toBe(0);
    expect(anthropicTokenEstimator(undefined as unknown as string)).toBe(0);
  });

  it("returns 0 for whitespace-only", () => {
    expect(anthropicTokenEstimator("   ")).toBe(0);
  });

  it("returns at least 1 for single word", () => {
    expect(anthropicTokenEstimator("hello")).toBeGreaterThanOrEqual(1);
  });

  it("uses 1.4x word multiplier", () => {
    // "one two three" = 3 words * 1.4 = 4.2 -> ceil = 5
    expect(anthropicTokenEstimator("one two three")).toBe(5);
  });

  it("accepts options parameter (ignored)", () => {
    const tokens = anthropicTokenEstimator("Hello", {
      model: "claude-sonnet-4-6",
    });
    expect(tokens).toBeGreaterThan(0);
  });
});
