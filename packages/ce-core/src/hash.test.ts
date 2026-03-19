import { describe, expect, it } from "vitest";
import { hash64 } from "./hash.js";

describe("hash64", () => {
  it("returns a string for empty input", () => {
    const result = hash64("");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });

  it("returns a string for non-empty input", () => {
    const result = hash64("hello world");
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);
  });

  it("is deterministic: same input always returns same hash", () => {
    const input = "deterministic test string";
    const h1 = hash64(input);
    const h2 = hash64(input);
    const h3 = hash64(input);
    expect(h1).toBe(h2);
    expect(h2).toBe(h3);
  });

  it("produces different hashes for different inputs", () => {
    const inputs = [
      "alpha",
      "beta",
      "gamma",
      "delta",
      "epsilon",
      "zeta",
      "eta",
      "theta",
      "iota",
      "kappa",
      "lambda",
    ];
    const hashes = inputs.map(s => hash64(s));
    const unique = new Set(hashes);
    expect(unique.size).toBe(inputs.length);
  });

  it("handles unicode and emoji characters", () => {
    const inputs = [
      "caf\u00e9",
      "\u4f60\u597d\u4e16\u754c",
      "\ud83d\ude80\ud83c\udf1f\ud83d\udd25",
      "\u00fc\u00f6\u00e4\u00df",
      "\u0410\u0411\u0412\u0413",
    ];
    for (const input of inputs) {
      const result = hash64(input);
      expect(typeof result).toBe("string");
      expect(result.length).toBeGreaterThan(0);
    }
    // All should produce distinct hashes
    const hashes = inputs.map(s => hash64(s));
    expect(new Set(hashes).size).toBe(inputs.length);
  });

  it("handles very long strings (10k+ chars)", () => {
    const longString = "a".repeat(10_000);
    const result = hash64(longString);
    expect(typeof result).toBe("string");
    expect(result.length).toBeGreaterThan(0);

    // Should differ from a shorter string of the same character
    const shortResult = hash64("a".repeat(100));
    expect(result).not.toBe(shortResult);
  });

  it("output format is base-36 (matches /^[0-9a-z]+$/)", () => {
    const testCases = ["", "hello", "test 123", "special!@#$%"];
    for (const input of testCases) {
      const result = hash64(input);
      expect(result).toMatch(/^[0-9a-z]+$/);
    }
  });

  it("collision resistance: 1000 unique strings all produce unique hashes", () => {
    const hashes = new Set<string>();
    for (let i = 0; i < 1000; i++) {
      hashes.add(hash64(`unique-string-${i}`));
    }
    expect(hashes.size).toBe(1000);
  });
});
