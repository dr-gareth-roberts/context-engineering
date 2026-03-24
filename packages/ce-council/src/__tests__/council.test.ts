import { describe, it, expect, vi } from "vitest";
import { createCouncil, ROLE_PRESETS } from "../council.js";
import type {
  CouncilLLMProvider,
  CouncilMember,
  CouncilConfig,
  MemberResponseEvent,
  RoundCompleteEvent,
} from "../types.js";

function mockProvider(prefix = "response"): CouncilLLMProvider {
  let callCount = 0;
  return {
    generate: vi.fn().mockImplementation(async () => {
      callCount++;
      return {
        text: `${prefix}-${callCount}`,
        model: "mock-model",
        usage: { totalTokens: 50 },
      };
    }),
  };
}

function member(
  id: string,
  role: string,
  provider?: CouncilLLMProvider
): CouncilMember {
  return {
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
    role,
    systemPrompt: `You are a ${role}.`,
    provider: provider ?? mockProvider(id),
  };
}

function baseConfig(overrides?: Partial<CouncilConfig>): CouncilConfig {
  const synthProvider = mockProvider("synthesis");
  return {
    members: [member("alice", "critic"), member("bob", "optimist")],
    strategy: "parallel",
    synthesizer: { provider: synthProvider },
    ...overrides,
  };
}

describe("createCouncil", () => {
  it("rejects councils with fewer than 2 members", () => {
    expect(() =>
      createCouncil({
        members: [member("solo", "critic")],
        strategy: "parallel",
        synthesizer: { provider: mockProvider() },
      })
    ).toThrow("at least 2 members");
  });
});

describe("parallel strategy", () => {
  it("produces a synthesis from independent responses", async () => {
    const council = createCouncil(baseConfig({ strategy: "parallel" }));
    const result = await council.deliberate({ query: "What is X?" });

    expect(result.synthesis).toContain("synthesis");
    expect(result.roundCount).toBe(1);
    expect(result.rounds).toHaveLength(1);
    expect(result.rounds[0].responses).toHaveLength(2);
    expect(result.strategy).toBe("parallel");
    expect(result.totalTokens).toBeGreaterThan(0);
    expect(result.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("calls each member exactly once", async () => {
    const aliceProvider = mockProvider("alice");
    const bobProvider = mockProvider("bob");
    const council = createCouncil(
      baseConfig({
        strategy: "parallel",
        members: [
          member("alice", "critic", aliceProvider),
          member("bob", "optimist", bobProvider),
        ],
      })
    );
    await council.deliberate({ query: "What is X?" });

    expect(aliceProvider.generate).toHaveBeenCalledTimes(1);
    expect(bobProvider.generate).toHaveBeenCalledTimes(1);
  });

  it("fires onMemberResponse and onRoundComplete callbacks", async () => {
    const memberEvents: MemberResponseEvent[] = [];
    const roundEvents: RoundCompleteEvent[] = [];

    const council = createCouncil(
      baseConfig({
        strategy: "parallel",
        onMemberResponse: e => memberEvents.push(e),
        onRoundComplete: e => roundEvents.push(e),
      })
    );
    await council.deliberate({ query: "Test?" });

    expect(memberEvents).toHaveLength(2);
    expect(roundEvents).toHaveLength(1);
    expect(roundEvents[0].responses).toHaveLength(2);
  });
});

describe("debate strategy", () => {
  it("runs multiple rounds with members seeing each other's responses", async () => {
    const council = createCouncil(
      baseConfig({ strategy: "debate", rounds: 2 })
    );
    const result = await council.deliberate({ query: "Debate this." });

    expect(result.roundCount).toBe(2);
    expect(result.rounds).toHaveLength(2);
    // Each member called twice (once per round)
    expect(result.rounds[0].responses).toHaveLength(2);
    expect(result.rounds[1].responses).toHaveLength(2);
  });

  it("debate prompts include prior responses", async () => {
    const provider = mockProvider("captured");
    const council = createCouncil(
      baseConfig({
        strategy: "debate",
        rounds: 2,
        members: [
          member("alice", "critic", provider),
          member("bob", "optimist", provider),
        ],
      })
    );
    await council.deliberate({ query: "Topic?" });

    // Round 2 calls should include text about "previous round"
    const round2Calls = (provider.generate as ReturnType<typeof vi.fn>).mock
      .calls;
    // Calls 3 and 4 are round 2 (0-indexed: calls at index 2 and 3)
    const round2Message = round2Calls[2][0][1].content as string;
    expect(round2Message).toContain("round 2");
  });
});

describe("stepladder strategy", () => {
  it("adds members one at a time", async () => {
    const council = createCouncil(
      baseConfig({
        strategy: "stepladder",
        members: [
          member("alice", "critic"),
          member("bob", "optimist"),
          member("charlie", "pragmatist"),
        ],
      })
    );
    const result = await council.deliberate({ query: "Step by step." });

    // One round per member
    expect(result.roundCount).toBe(3);
    // First round has 1 response, second has 2, third has 3
    expect(result.rounds[0].responses).toHaveLength(1);
    expect(result.rounds[1].responses).toHaveLength(2);
    expect(result.rounds[2].responses).toHaveLength(3);
  });
});

describe("delphi strategy", () => {
  it("runs anonymous rounds with convergence scoring", async () => {
    const council = createCouncil(
      baseConfig({ strategy: "delphi", rounds: 3 })
    );
    const result = await council.deliberate({ query: "Anonymous debate." });

    expect(result.strategy).toBe("delphi");
    expect(result.convergenceScore).toBeDefined();
    expect(result.roundCount).toBeGreaterThanOrEqual(1);
    expect(result.roundCount).toBeLessThanOrEqual(3);
  });

  it("converges early when responses are identical", async () => {
    // Provider that always returns the same text
    const identicalProvider: CouncilLLMProvider = {
      generate: vi.fn().mockResolvedValue({
        text: "exactly the same response every time with enough words to match",
        model: "mock",
        usage: { totalTokens: 20 },
      }),
    };

    const council = createCouncil({
      members: [
        member("alice", "critic", identicalProvider),
        member("bob", "optimist", identicalProvider),
      ],
      strategy: "delphi",
      rounds: 5,
      convergenceThreshold: 0.8,
      synthesizer: { provider: identicalProvider },
    });

    const result = await council.deliberate({ query: "Agree?" });

    expect(result.convergedEarly).toBe(true);
    expect(result.roundCount).toBe(1);
  });
});

describe("context packing integration", () => {
  it("packs context items when budget is provided", async () => {
    const council = createCouncil(baseConfig({ strategy: "parallel" }));
    const result = await council.deliberate({
      query: "Analyze this.",
      contextItems: [
        { id: "doc1", content: "Important document content", priority: 10 },
        { id: "doc2", content: "Supporting evidence", priority: 5 },
      ],
      budget: { maxTokens: 1000 },
    });

    expect(result.synthesis).toBeDefined();
  });

  it("passes context without packing when no budget provided", async () => {
    const provider = mockProvider("ctx");
    const council = createCouncil(
      baseConfig({
        strategy: "parallel",
        members: [
          member("alice", "critic", provider),
          member("bob", "optimist", provider),
        ],
      })
    );

    await council.deliberate({
      query: "Analyze this.",
      contextItems: [
        { id: "doc1", content: "Document one", priority: 10 },
        { id: "doc2", content: "Document two", priority: 5 },
      ],
    });

    const firstCall = (provider.generate as ReturnType<typeof vi.fn>).mock
      .calls[0];
    const userMessage = firstCall[0][1].content as string;
    expect(userMessage).toContain("Document one");
    expect(userMessage).toContain("Document two");
  });
});

describe("token tracking", () => {
  it("tracks tokens per member and total", async () => {
    const council = createCouncil(
      baseConfig({ strategy: "debate", rounds: 2 })
    );
    const result = await council.deliberate({ query: "Track tokens." });

    expect(result.totalTokens).toBeGreaterThan(0);
    expect(result.tokensByMember["alice"]).toBeGreaterThan(0);
    expect(result.tokensByMember["bob"]).toBeGreaterThan(0);
    expect(result.tokensByMember["_synthesizer"]).toBeGreaterThan(0);
  });
});

describe("ROLE_PRESETS", () => {
  it("provides system prompts for common expert roles", () => {
    expect(Object.keys(ROLE_PRESETS)).toContain("critic");
    expect(Object.keys(ROLE_PRESETS)).toContain("optimist");
    expect(Object.keys(ROLE_PRESETS)).toContain("pragmatist");
    expect(Object.keys(ROLE_PRESETS)).toContain("innovator");
    expect(Object.keys(ROLE_PRESETS)).toContain("devils-advocate");
    expect(Object.keys(ROLE_PRESETS)).toContain("user-advocate");
    expect(Object.keys(ROLE_PRESETS)).toContain("risk-analyst");
    expect(Object.keys(ROLE_PRESETS)).toContain("domain-expert");

    for (const preset of Object.values(ROLE_PRESETS)) {
      expect(preset.role).toBeTruthy();
      expect(preset.systemPrompt.length).toBeGreaterThan(20);
    }
  });
});

describe("round override", () => {
  it("allows overriding rounds per deliberation call", async () => {
    const council = createCouncil(
      baseConfig({ strategy: "debate", rounds: 5 })
    );
    const result = await council.deliberate({
      query: "Override rounds.",
      rounds: 2,
    });
    expect(result.roundCount).toBe(2);
  });
});
