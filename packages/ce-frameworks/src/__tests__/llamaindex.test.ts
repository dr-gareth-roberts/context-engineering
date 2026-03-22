import { describe, it, expect, vi } from "vitest";
import { withContextLlamaIndex } from "../llamaindex.js";
import type { LlamaIndexLike, LlamaIndexMessage } from "../llamaindex.js";

function createMockLlm(response = "mock response"): LlamaIndexLike & {
  lastMessages: LlamaIndexMessage[];
} {
  const llm: LlamaIndexLike & { lastMessages: LlamaIndexMessage[] } = {
    model: "gpt-4o",
    lastMessages: [],
    async chat(params: { messages: LlamaIndexMessage[] }) {
      llm.lastMessages = params.messages;
      return { message: { role: "assistant", content: response } };
    },
  };
  return llm;
}

function makeMessages(count: number): LlamaIndexMessage[] {
  const msgs: LlamaIndexMessage[] = [
    { role: "system", content: "You are helpful." },
  ];
  for (let i = 1; i < count; i++) {
    const role = i % 2 === 1 ? "user" : "assistant";
    msgs.push({ role, content: `Message ${i}: ${"word ".repeat(50).trim()}` });
  }
  return msgs;
}

describe("withContextLlamaIndex", () => {
  it("packs messages when over budget", async () => {
    const llm = createMockLlm();
    const wrapped = withContextLlamaIndex(llm, {
      budget: 200,
      reserveTokens: 0,
      log: false,
    });

    const messages = makeMessages(20);
    await wrapped.chat({ messages });

    expect(llm.lastMessages.length).toBeLessThan(messages.length);
  });

  it("passes through messages unchanged when under budget", async () => {
    const llm = createMockLlm();
    const wrapped = withContextLlamaIndex(llm, {
      budget: 100_000,
      log: false,
    });

    const messages: LlamaIndexMessage[] = [
      { role: "system", content: "Be helpful" },
      { role: "user", content: "Hi" },
    ];
    await wrapped.chat({ messages });

    expect(llm.lastMessages).toHaveLength(2);
    expect(llm.lastMessages[0]).toBe(messages[0]);
  });

  it("extracts model name from model property", async () => {
    const packListener = vi.fn();
    const llm = createMockLlm();
    llm.model = "gpt-4-turbo";

    const wrapped = withContextLlamaIndex(llm, {
      budget: 100_000,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.chat({ messages: [{ role: "user", content: "hi" }] });
    expect(packListener.mock.calls[0][0].model).toBe("gpt-4-turbo");
  });

  it("extracts model name from metadata", async () => {
    const packListener = vi.fn();
    const llm: LlamaIndexLike & { lastMessages: LlamaIndexMessage[] } = {
      metadata: { model: "claude-3-sonnet" },
      lastMessages: [],
      async chat(params: { messages: LlamaIndexMessage[] }) {
        llm.lastMessages = params.messages;
        return { message: { role: "assistant", content: "ok" } };
      },
    };

    const wrapped = withContextLlamaIndex(llm, {
      budget: 100_000,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.chat({ messages: [{ role: "user", content: "hi" }] });
    expect(packListener.mock.calls[0][0].model).toBe("claude-3-sonnet");
  });

  it("fires framework event as llamaindex", async () => {
    const packListener = vi.fn();
    const llm = createMockLlm();
    const wrapped = withContextLlamaIndex(llm, {
      budget: 200,
      reserveTokens: 0,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.chat({ messages: makeMessages(15) });
    expect(packListener.mock.calls[0][0].framework).toBe("llamaindex");
  });

  it("preserves extra chat params", async () => {
    let capturedParams: Record<string, unknown> = {};
    const llm: LlamaIndexLike = {
      model: "gpt-4o",
      async chat(params: {
        messages: LlamaIndexMessage[];
        [key: string]: unknown;
      }) {
        capturedParams = params;
        return { message: { role: "assistant", content: "ok" } };
      },
    };

    const wrapped = withContextLlamaIndex(llm, {
      budget: 100_000,
      log: false,
    });

    await wrapped.chat({
      messages: [{ role: "user", content: "hi" }],
      temperature: 0.5,
    } as { messages: LlamaIndexMessage[]; temperature: number });

    expect(capturedParams.temperature).toBe(0.5);
  });

  it("falls through on error", async () => {
    const llm = createMockLlm();
    const errorListener = vi.fn();

    const wrapped = withContextLlamaIndex(llm, {
      budget: -1,
      reserveTokens: 0,
      log: false,
      on: { error: errorListener },
    });

    const result = await wrapped.chat({
      messages: [{ role: "user", content: "hi" }],
    });
    expect(result).toBeDefined();
  });
});
