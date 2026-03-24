import { describe, it, expect } from "vitest";
import { computeConvergence } from "../convergence.js";
import type { MemberResponse } from "../types.js";

function response(text: string, id = "m1"): MemberResponse {
  return {
    memberId: id,
    memberName: "Test",
    role: "test",
    response: text,
    model: "test",
    tokensUsed: 0,
  };
}

describe("computeConvergence", () => {
  it("returns 1 for a single response", () => {
    expect(computeConvergence([response("hello world")])).toBe(1);
  });

  it("returns 1 for identical responses", () => {
    const score = computeConvergence([
      response(
        "microservices are the best approach for this architecture",
        "a"
      ),
      response(
        "microservices are the best approach for this architecture",
        "b"
      ),
    ]);
    expect(score).toBe(1);
  });

  it("returns higher score for similar responses than dissimilar ones", () => {
    const similar = computeConvergence([
      response(
        "microservices provide better scalability and isolation for this use case",
        "a"
      ),
      response(
        "microservices offer better scalability and service isolation benefits",
        "b"
      ),
    ]);
    const dissimilar = computeConvergence([
      response(
        "the database schema needs normalization and proper indexing",
        "a"
      ),
      response(
        "frontend components should use react hooks with proper memoization",
        "b"
      ),
    ]);
    expect(similar).toBeGreaterThan(dissimilar);
    expect(similar).toBeGreaterThan(0.3);
  });

  it("returns low score for very different responses", () => {
    const score = computeConvergence([
      response(
        "the database schema needs normalization and proper indexing",
        "a"
      ),
      response(
        "frontend components should use react hooks with proper memoization",
        "b"
      ),
    ]);
    expect(score).toBeLessThan(0.3);
  });

  it("handles empty responses", () => {
    expect(computeConvergence([])).toBe(1);
  });

  it("handles three or more members with pairwise comparison", () => {
    const score = computeConvergence([
      response("use microservices for scalability", "a"),
      response("use microservices for better deployment", "b"),
      response("monolith is simpler and cheaper to operate", "c"),
    ]);
    // Two agree-ish, one disagrees — should be moderate
    expect(score).toBeGreaterThan(0.1);
    expect(score).toBeLessThan(0.8);
  });
});
