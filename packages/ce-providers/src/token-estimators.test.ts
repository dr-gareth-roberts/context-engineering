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
});

describe("anthropicTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = anthropicTokenEstimator("Hello, world!");
    expect(tokens).toBeGreaterThan(0);
  });

  it("returns 0 for empty string", () => {
    expect(anthropicTokenEstimator("")).toBe(0);
  });

  it("returns 0 for whitespace-only", () => {
    expect(anthropicTokenEstimator("   ")).toBe(0);
  });

  it("returns at least 1 for single word", () => {
    expect(anthropicTokenEstimator("hello")).toBeGreaterThanOrEqual(1);
  });

  it("uses 1.4x word multiplier", () => {
    // "one two three" = 3 words * 1.4 = 4.2 → ceil = 5
    expect(anthropicTokenEstimator("one two three")).toBe(5);
  });
});
