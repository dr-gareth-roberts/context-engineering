import { describe, expect, it } from "vitest";
import { estimateTokens, defaultTokenEstimator } from "./estimate.js";

describe("defaultTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = defaultTokenEstimator("hello world");
    expect(tokens).toBeGreaterThan(0);
  });

  it("returns 0 for empty string", () => {
    expect(defaultTokenEstimator("")).toBe(0);
  });

  it("returns 0 for whitespace-only string", () => {
    expect(defaultTokenEstimator("   ")).toBe(0);
  });

  it("returns at least 1 for single word", () => {
    expect(defaultTokenEstimator("hello")).toBeGreaterThanOrEqual(1);
  });

  it("scales roughly with word count", () => {
    const short = defaultTokenEstimator("one two three");
    const long = defaultTokenEstimator(
      "one two three four five six seven eight nine ten"
    );
    expect(long).toBeGreaterThan(short);
  });
});

describe("estimateTokens", () => {
  it("uses default estimator", () => {
    expect(estimateTokens("hello world")).toBeGreaterThan(0);
  });

  it("returns 0 for null-ish input", () => {
    expect(estimateTokens(null as unknown as string)).toBe(0);
    expect(estimateTokens(undefined as unknown as string)).toBe(0);
  });

  it("uses custom estimator", () => {
    const custom = (text: string) => text.length;
    expect(estimateTokens("hello", { estimator: custom })).toBe(5);
  });
});

describe("defaultTokenEstimator edge cases", () => {
  it("returns 0 for newlines-only string", () => {
    expect(defaultTokenEstimator("\n\n\n")).toBe(0);
  });

  it("returns > 0 for unicode/emoji text", () => {
    expect(
      defaultTokenEstimator("\u{1F389}\u{1F389}\u{1F389}")
    ).toBeGreaterThan(0);
  });
});
