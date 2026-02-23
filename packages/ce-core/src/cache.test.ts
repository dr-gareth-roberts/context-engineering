import { describe, expect, it, vi } from "vitest";
import { createCachedEstimator } from "./cache.js";

describe("createCachedEstimator", () => {
  it("caches repeated calls", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner, { maxSize: 100 });

    const first = cached("hello");
    const second = cached("hello");

    expect(first).toBe(second);
    expect(inner).toHaveBeenCalledTimes(1);
  });

  it("handles different inputs", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner, { maxSize: 100 });

    cached("hello");
    cached("world");

    expect(inner).toHaveBeenCalledTimes(2);
  });

  it("evicts oldest entries when exceeding maxSize", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner, { maxSize: 2 });

    cached("a");
    cached("b");
    cached("c");
    cached("a");

    expect(inner).toHaveBeenCalledTimes(4);
  });

  it("uses default maxSize of 1000", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner);

    cached("test");
    cached("test");

    expect(inner).toHaveBeenCalledTimes(1);
  });
});
