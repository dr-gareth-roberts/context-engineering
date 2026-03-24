import { describe, it, expect } from "vitest";
import {
  buildInitialPrompt,
  buildDebatePrompt,
  buildStepladderPrompt,
  buildDelphiPrompt,
  buildSynthesisPrompt,
} from "../prompts.js";
import type { MemberResponse } from "../types.js";

const mockResponse = (
  name: string,
  role: string,
  text: string
): MemberResponse => ({
  memberId: name.toLowerCase(),
  memberName: name,
  role,
  response: text,
  model: "test",
  tokensUsed: 10,
});

describe("buildInitialPrompt", () => {
  it("builds a simple prompt without context", () => {
    const messages = buildInitialPrompt("You are an expert.", "What is X?");
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe("system");
    expect(messages[0].content).toBe("You are an expert.");
    expect(messages[1].role).toBe("user");
    expect(messages[1].content).toBe("What is X?");
  });

  it("includes context when provided", () => {
    const messages = buildInitialPrompt(
      "You are an expert.",
      "What is X?",
      "Background: X is a thing."
    );
    expect(messages[1].content).toContain("Background: X is a thing.");
    expect(messages[1].content).toContain("What is X?");
  });
});

describe("buildDebatePrompt", () => {
  it("includes prior responses with attribution", () => {
    const prior = [mockResponse("Alice", "critic", "I think X is bad.")];
    const messages = buildDebatePrompt("Be fair.", "What about X?", prior, 2);
    expect(messages[1].content).toContain("**Alice** (critic):");
    expect(messages[1].content).toContain("I think X is bad.");
    expect(messages[1].content).toContain("round 2");
  });
});

describe("buildStepladderPrompt", () => {
  it("shows prior discussion for later members", () => {
    const prior = [
      mockResponse("Alice", "critic", "X is bad."),
      mockResponse("Bob", "optimist", "X has potential."),
    ];
    const messages = buildStepladderPrompt(
      "Fresh perspective.",
      "What is X?",
      prior
    );
    expect(messages[1].content).toContain("**Alice** (critic):");
    expect(messages[1].content).toContain("**Bob** (optimist):");
    expect(messages[1].content).toContain("fresh perspective");
  });

  it("builds initial prompt when no prior discussion", () => {
    const messages = buildStepladderPrompt(
      "Fresh perspective.",
      "What is X?",
      []
    );
    expect(messages[1].content).not.toContain("experts have already");
  });
});

describe("buildDelphiPrompt", () => {
  it("anonymizes responses", () => {
    const prior = [
      mockResponse("Alice", "critic", "X is bad."),
      mockResponse("Bob", "optimist", "X is great."),
    ];
    const messages = buildDelphiPrompt("Be fair.", "What about X?", prior, 2);
    expect(messages[1].content).not.toContain("Alice");
    expect(messages[1].content).not.toContain("Bob");
    expect(messages[1].content).toContain("Expert 1");
    expect(messages[1].content).toContain("Expert 2");
    expect(messages[1].content).toContain("anonymous");
  });
});

describe("buildSynthesisPrompt", () => {
  it("includes the last round's responses", () => {
    const rounds = [
      {
        round: 1,
        responses: [mockResponse("Alice", "critic", "First take.")],
      },
      {
        round: 2,
        responses: [mockResponse("Alice", "critic", "Refined take.")],
      },
    ];
    const messages = buildSynthesisPrompt("What is X?", rounds);
    expect(messages[0].content).toContain("synthesis expert");
    expect(messages[1].content).toContain("Refined take.");
    expect(messages[1].content).toContain("2 round(s)");
  });

  it("uses custom system prompt when provided", () => {
    const rounds = [
      {
        round: 1,
        responses: [mockResponse("Alice", "critic", "Take.")],
      },
    ];
    const messages = buildSynthesisPrompt(
      "What is X?",
      rounds,
      "You are the supreme arbiter."
    );
    expect(messages[0].content).toBe("You are the supreme arbiter.");
  });
});
