import { describe, it, expect, vi } from "vitest";
import { withContextAnthropic } from "./anthropic.js";

function createMockAnthropicClient() {
  const createFn = vi.fn().mockResolvedValue({
    id: "msg_123",
    content: [{ type: "text", text: "Hello!" }],
    role: "assistant",
  });

  return {
    messages: {
      create: createFn,
    },
    // Other properties
    completions: { create: vi.fn() },
    _createFn: createFn,
  };
}

describe("withContextAnthropic", () => {
  it("wraps the client and intercepts messages.create", async () => {
    const mock = createMockAnthropicClient();
    const client = withContextAnthropic(mock, { log: false });

    const result = await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      system: "You are helpful",
      messages: [
        { role: "user", content: "Hello" },
      ],
    });

    expect(result).toEqual({
      id: "msg_123",
      content: [{ type: "text", text: "Hello!" }],
      role: "assistant",
    });
    expect(mock._createFn).toHaveBeenCalledOnce();
  });

  it("preserves the system prompt as a separate parameter", async () => {
    const mock = createMockAnthropicClient();
    const client = withContextAnthropic(mock, { log: false });

    await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      system: "You are a coding assistant",
      messages: [
        { role: "user", content: "Write me a function" },
      ],
    });

    const passedParams = mock._createFn.mock.calls[0][0] as Record<string, unknown>;
    expect(passedParams.system).toBe("You are a coding assistant");
    const messages = passedParams.messages as Array<{ role: string }>;
    // System should not appear in messages array
    expect(messages.every((m) => m.role !== "system")).toBe(true);
  });

  it("trims messages when they exceed the budget", async () => {
    const mock = createMockAnthropicClient();
    const client = withContextAnthropic(mock, {
      budget: 100,
      reserveTokens: 10,
      log: false,
    });

    const longMessages = Array.from({ length: 20 }, (_, i) => ({
      role: (i % 2 === 0 ? "user" : "assistant") as "user" | "assistant",
      content: `This is message number ${i} with enough words to consume several tokens`,
    }));

    await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      system: "You are helpful",
      messages: longMessages,
    });

    const passedParams = mock._createFn.mock.calls[0][0] as Record<string, unknown>;
    const messages = passedParams.messages as Array<{ role: string }>;
    expect(messages.length).toBeLessThan(longMessages.length);
  });

  it("emits pack events to listeners", async () => {
    const mock = createMockAnthropicClient();
    const packListener = vi.fn();
    const client = withContextAnthropic(mock, {
      log: false,
      on: { pack: packListener },
    });

    await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      messages: [{ role: "user", content: "Hello" }],
    });

    expect(packListener).toHaveBeenCalledOnce();
    const event = packListener.mock.calls[0][0];
    expect(event.model).toBe("claude-sonnet-4-6");
  });

  it("passes through non-messages methods untouched", () => {
    const mock = createMockAnthropicClient();
    const client = withContextAnthropic(mock, { log: false });

    expect(client.completions.create).toBe(mock.completions.create);
  });

  it("handles missing system prompt", async () => {
    const mock = createMockAnthropicClient();
    const client = withContextAnthropic(mock, { log: false });

    await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      messages: [{ role: "user", content: "Hello" }],
    });

    expect(mock._createFn).toHaveBeenCalledOnce();
  });
});
