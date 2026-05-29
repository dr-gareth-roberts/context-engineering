import { describe, it, expect, vi } from "vitest";
import { createCouncil } from "../council.js";
import type { CouncilLLMProvider, CouncilMember } from "../types.js";

/**
 * Regression tests for `convergedEarly` honouring the per-call `rounds`
 * override (DeliberateOptions.rounds), not the council's configured rounds.
 *
 * Bug: `convergedEarly` was computed against `config.rounds`, so a delphi
 * deliberation that ran its FULL overridden budget and converged on the last
 * allotted round was still reported as `convergedEarly: true`.
 */

/**
 * A provider whose response is keyed on its OWN call count. In delphi each
 * member is called exactly once per round, so `callCount === round`. This makes
 * convergence deterministic without reasoning about Promise.all ordering.
 *
 * `convergeAtRound`: from this round onward the provider returns a fixed,
 * shared phrase so all members' responses are identical (Jaccard = 1.0).
 */
function roundKeyedProvider(
  uniquePrefix: string,
  convergeAtRound: number
): CouncilLLMProvider {
  let callCount = 0;
  return {
    generate: vi.fn().mockImplementation(async () => {
      callCount++;
      const round = callCount;
      const text =
        round >= convergeAtRound
          ? "converged consensus answer final agreement reached"
          : `${uniquePrefix} round ${round} unique divergent opinion text`;
      return { text, model: "mock-model", usage: { totalTokens: 30 } };
    }),
  };
}

function member(
  id: string,
  role: string,
  provider: CouncilLLMProvider
): CouncilMember {
  return {
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
    role,
    systemPrompt: `You are a ${role}.`,
    provider,
  };
}

describe("convergedEarly with per-call rounds override", () => {
  it("reports convergedEarly=false when delphi runs its FULL overridden budget and converges on the last allotted round", async () => {
    // Members diverge in round 1, converge in round 2.
    const council = createCouncil({
      members: [
        member("alice", "critic", roundKeyedProvider("alice", 2)),
        member("bob", "optimist", roundKeyedProvider("bob", 2)),
      ],
      strategy: "delphi",
      rounds: 5, // configured budget
      convergenceThreshold: 0.8,
      // Separate synthesizer provider so its post-strategy call is unrelated.
      synthesizer: { provider: roundKeyedProvider("synth", 99) },
    });

    // Override the budget down to 2; convergence happens on round 2 (the last
    // allotted round), so deliberation did NOT stop early.
    const result = await council.deliberate({ query: "Agree?", rounds: 2 });

    expect(result.roundCount).toBe(2);
    expect(result.convergenceScore).toBeGreaterThanOrEqual(0.8);
    // With the bug this was true (2 < config.rounds(5)); correct value is false
    // (2 < effectiveConfig.rounds(2)).
    expect(result.convergedEarly).toBe(false);
  });

  it("reports convergedEarly=true when convergence happens before the overridden budget is exhausted", async () => {
    // Same providers (converge in round 2), but a larger overridden budget (3).
    const council = createCouncil({
      members: [
        member("alice", "critic", roundKeyedProvider("alice", 2)),
        member("bob", "optimist", roundKeyedProvider("bob", 2)),
      ],
      strategy: "delphi",
      rounds: 5,
      convergenceThreshold: 0.8,
      synthesizer: { provider: roundKeyedProvider("synth", 99) },
    });

    const result = await council.deliberate({ query: "Agree?", rounds: 3 });

    expect(result.roundCount).toBe(2);
    expect(result.convergenceScore).toBeGreaterThanOrEqual(0.8);
    // Converged on round 2 of an overridden 3-round budget => stopped early.
    expect(result.convergedEarly).toBe(true);
  });
});
