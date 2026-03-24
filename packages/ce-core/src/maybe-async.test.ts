import { describe, it, expect } from "vitest";
import { chain, all } from "./maybe-async.js";

describe("chain", () => {
  it("returns sync result when given a sync value", () => {
    const result = chain(42, v => v * 2);
    // Should NOT be a Promise
    expect(result).toBe(84);
    expect(result instanceof Promise).toBe(false);
  });

  it("returns a Promise when given a Promise", async () => {
    const result = chain(Promise.resolve(42), v => v * 2);
    expect(result instanceof Promise).toBe(true);
    expect(await result).toBe(84);
  });

  it("returns a Promise when the fn returns a Promise", async () => {
    const result = chain(Promise.resolve(10), v => Promise.resolve(v + 5));
    expect(result instanceof Promise).toBe(true);
    expect(await result).toBe(15);
  });

  it("works with nested chains", () => {
    const result = chain(
      chain(2, v => v + 3),
      v => v * 10
    );
    expect(result).toBe(50);
    expect(result instanceof Promise).toBe(false);
  });

  it("works with nested async chains", async () => {
    const result = chain(
      chain(Promise.resolve(2), v => v + 3),
      v => v * 10
    );
    expect(result instanceof Promise).toBe(true);
    expect(await result).toBe(50);
  });
});

describe("all", () => {
  it("returns sync array when all values are sync", () => {
    const result = all([1, 2, 3]);
    expect(result instanceof Promise).toBe(false);
    expect(result).toEqual([1, 2, 3]);
  });

  it("returns Promise when any value is a Promise", async () => {
    const result = all([1, Promise.resolve(2), 3]);
    expect(result instanceof Promise).toBe(true);
    expect(await result).toEqual([1, 2, 3]);
  });

  it("returns sync empty array for empty input", () => {
    const result = all([]);
    expect(result instanceof Promise).toBe(false);
    expect(result).toEqual([]);
  });
});
