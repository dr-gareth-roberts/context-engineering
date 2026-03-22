import { describe, it, expect, vi, beforeEach } from "vitest";
import { withContext } from "./openai.js";

/** Minimal mock of the OpenAI client structure. */
function createMockOpenAIClient() {
  const createFn = vi.fn().mockResolvedValue({
    id: "chatcmpl-123",
    choices: [{ message: { role: "assistant", content: "Hello!" } }],
  });

  return {
    chat: {
      completions: {
        create: createFn,
      },
    },
    // Other properties on the client should pass through
    models: { list: vi.fn() },
    _createFn: createFn,
  };
}

describe("withContext (OpenAI)", () => {
  it("wraps the client and intercepts chat.completions.create", async () => {
    const mock = createMockOpenAIClient();
    const client = withContext(mock, { log: false });

    const result = await client.chat.completions.create({
      model: "gpt-4o",
      messages: [
        { role: "system", content: "You are helpful" },
        { role: "user", content: "Hello" },
      ],
    });

    expect(result).toEqual({
      id: "chatcmpl-123",
      choices: [{ message: { role: "assistant", content: "Hello!" } }],
    });
    expect(mock._createFn).toHaveBeenCalledOnce();
  });

  it("passes through messages unchanged when they fit the budget", async () => {
    const mock = createMockOpenAIClient();
    const client = withContext(mock, { log: false });

    await client.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "short message" }],
    });

    const passedParams = mock._createFn.mock.calls[0][0] as Record<
      string,
      unknown
    >;
    const messages = passedParams.messages as Array<{
      role: string;
      content: string;
    }>;
    expect(messages).toHaveLength(1);
    expect(messages[0].content).toBe("short message");
  });

  it("trims messages when they exceed the budget", async () => {
    const mock = createMockOpenAIClient();
    // Tiny budget to force trimming
    const client = withContext(mock, {
      budget: 100,
      reserveTokens: 10,
      log: false,
    });

    const longMessages = [
      { role: "system" as const, content: "You are a helpful assistant." },
      ...Array.from({ length: 20 }, (_, i) => ({
        role: (i % 2 === 0 ? "user" : "assistant") as "user" | "assistant",
        content: `This is message number ${i} with enough words to consume several tokens in the budget`,
      })),
    ];

    await client.chat.completions.create({
      model: "gpt-4o",
      messages: longMessages,
    });

    const passedParams = mock._createFn.mock.calls[0][0] as Record<
      string,
      unknown
    >;
    const messages = passedParams.messages as Array<{ role: string }>;
    expect(messages.length).toBeLessThan(longMessages.length);
    // System message should always be kept
    expect(messages[0].role).toBe("system");
  });

  it("emits pack events to listeners", async () => {
    const mock = createMockOpenAIClient();
    const packListener = vi.fn();
    const client = withContext(mock, {
      log: false,
      on: { pack: packListener },
    });

    await client.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "Hello" }],
    });

    expect(packListener).toHaveBeenCalledOnce();
    const event = packListener.mock.calls[0][0];
    expect(event.model).toBe("gpt-4o");
    expect(event.totalMessages).toBe(1);
    expect(event.keptMessages).toBe(1);
  });

  it("passes through non-chat methods untouched", () => {
    const mock = createMockOpenAIClient();
    const client = withContext(mock, { log: false });

    expect(client.models.list).toBe(mock.models.list);
  });

  it("falls through to original on packing error", async () => {
    const mock = createMockOpenAIClient();
    const errorHandler = vi.fn();
    const client = withContext(mock, {
      log: false,
      on: { error: errorHandler },
      // Invalid budget to trigger an error in pack
      budget: -1,
      reserveTokens: 0,
    });

    // This should still call the original function even if packing fails
    await client.chat.completions.create({
      model: "gpt-4o",
      messages: [{ role: "user", content: "Hello" }],
    });

    expect(mock._createFn).toHaveBeenCalledOnce();
  });

  it("handles empty messages array", async () => {
    const mock = createMockOpenAIClient();
    const client = withContext(mock, { log: false });

    await client.chat.completions.create({
      model: "gpt-4o",
      messages: [],
    });

    // Should pass through without packing
    const passedParams = mock._createFn.mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(passedParams.messages).toEqual([]);
  });
});
