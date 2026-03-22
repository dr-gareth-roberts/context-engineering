import { describe, it, expect, vi } from "vitest";
import { withContextLangChain } from "../langchain.js";
import type { LangChainLike } from "../langchain.js";

/** Create a mock LangChain ChatModel. */
function createMockModel(response = "mock response"): LangChainLike & {
  lastMessages: unknown[];
} {
  const model: LangChainLike & { lastMessages: unknown[] } = {
    model_name: "gpt-4o",
    lastMessages: [],
    async invoke(messages: unknown[]) {
      model.lastMessages = messages;
      return { content: response };
    },
  };
  return model;
}

/** Create a LangChain-style message with _getType(). */
function langChainMsg(type: string, content: string) {
  return {
    content,
    _getType() {
      return type;
    },
  };
}

/** Create many messages to exceed budget. */
function manyMessages(count: number) {
  const msgs = [langChainMsg("system", "You are helpful.")];
  for (let i = 1; i < count; i++) {
    const type = i % 2 === 1 ? "human" : "ai";
    const content = `Message ${i}: ${"word ".repeat(50).trim()}`;
    msgs.push(langChainMsg(type, content));
  }
  return msgs;
}

describe("withContextLangChain", () => {
  it("proxies invoke and packs messages when over budget", async () => {
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 200,
      reserveTokens: 0,
      log: false,
    });

    const messages = manyMessages(20);
    await wrapped.invoke(messages);

    // Should have fewer messages after packing
    expect(model.lastMessages.length).toBeLessThan(messages.length);
  });

  it("passes through messages unchanged when under budget", async () => {
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
    });

    const messages = [
      langChainMsg("system", "Be helpful"),
      langChainMsg("human", "Hi"),
    ];
    await wrapped.invoke(messages);

    // Original messages passed through (same objects)
    expect(model.lastMessages).toHaveLength(2);
    expect(model.lastMessages[0]).toBe(messages[0]);
  });

  it("fires event listeners", async () => {
    const packListener = vi.fn();
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 200,
      reserveTokens: 0,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.invoke(manyMessages(15));

    expect(packListener).toHaveBeenCalledTimes(1);
    expect(packListener.mock.calls[0][0].framework).toBe("langchain");
  });

  it("handles _getType() message format", async () => {
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
    });

    const messages = [
      langChainMsg("system", "system prompt"),
      langChainMsg("human", "user message"),
      langChainMsg("ai", "ai response"),
    ];
    await wrapped.invoke(messages);

    expect(model.lastMessages).toHaveLength(3);
  });

  it("handles .type message format", async () => {
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
    });

    const messages = [
      { content: "hello", type: "human" },
      { content: "hi", type: "ai" },
    ];
    await wrapped.invoke(messages);

    expect(model.lastMessages).toHaveLength(2);
  });

  it("handles .role message format", async () => {
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
    });

    const messages = [
      { content: "hello", role: "user" },
      { content: "hi", role: "assistant" },
    ];
    await wrapped.invoke(messages);

    expect(model.lastMessages).toHaveLength(2);
  });

  it("falls through gracefully on error", async () => {
    const model = createMockModel();
    const errorListener = vi.fn();

    // Force an error by making packMessages fail via broken config
    const wrapped = withContextLangChain(model, {
      budget: -1, // Will cause issues
      reserveTokens: 0,
      log: false,
      on: { error: errorListener },
    });

    const messages = manyMessages(5);
    // Should not throw — falls through to original
    const result = await wrapped.invoke(messages);
    expect(result).toEqual({ content: "mock response" });
  });

  it("passes empty messages through without interception", async () => {
    const model = createMockModel();
    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
    });

    await wrapped.invoke([]);
    expect(model.lastMessages).toHaveLength(0);
  });

  it("extracts model name from model_name property", async () => {
    const packListener = vi.fn();
    const model = createMockModel();
    model.model_name = "claude-3-opus";

    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.invoke([langChainMsg("human", "hi")]);
    expect(packListener.mock.calls[0][0].model).toBe("claude-3-opus");
  });

  it("extracts model name from modelName property", async () => {
    const packListener = vi.fn();
    const model: LangChainLike & { lastMessages: unknown[] } = {
      modelName: "gpt-4-turbo",
      lastMessages: [],
      async invoke(messages: unknown[]) {
        model.lastMessages = messages;
        return { content: "ok" };
      },
    };

    const wrapped = withContextLangChain(model, {
      budget: 100_000,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.invoke([langChainMsg("human", "hi")]);
    expect(packListener.mock.calls[0][0].model).toBe("gpt-4-turbo");
  });

  it("preserves non-invoke properties on the proxy", () => {
    const model = createMockModel();
    (model as Record<string, unknown>).temperature = 0.5;

    const wrapped = withContextLangChain(model, { log: false });
    expect((wrapped as Record<string, unknown>).temperature).toBe(0.5);
    expect(wrapped.model_name).toBe("gpt-4o");
  });
});
