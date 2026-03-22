import { describe, it, expect, vi } from "vitest";
import { withContextCrewAI } from "../crewai.js";
import type { CrewAILike } from "../crewai.js";

function createMockLlm(methods: ("invoke" | "call")[] = ["invoke", "call"]) {
  const llm: CrewAILike & {
    lastMessages: unknown[];
    invokeCount: number;
    callCount: number;
  } = {
    model_name: "gpt-4o",
    lastMessages: [],
    invokeCount: 0,
    callCount: 0,
  };

  if (methods.includes("invoke")) {
    llm.invoke = async (messages: unknown[]) => {
      llm.lastMessages = messages;
      llm.invokeCount++;
      return { content: "invoked" };
    };
  }

  if (methods.includes("call")) {
    llm.call = async (messages: unknown[]) => {
      llm.lastMessages = messages;
      llm.callCount++;
      return { content: "called" };
    };
  }

  return llm;
}

function manyMessages(count: number) {
  const msgs: { role: string; content: string }[] = [
    { role: "system", content: "You are helpful." },
  ];
  for (let i = 1; i < count; i++) {
    const role = i % 2 === 1 ? "user" : "assistant";
    msgs.push({ role, content: `Message ${i}: ${"word ".repeat(50).trim()}` });
  }
  return msgs;
}

describe("withContextCrewAI", () => {
  it("intercepts invoke method and packs messages", async () => {
    const llm = createMockLlm(["invoke"]);
    const wrapped = withContextCrewAI(llm, {
      budget: 200,
      reserveTokens: 0,
      log: false,
    });

    const messages = manyMessages(20);
    await wrapped.invoke!(messages);

    expect(llm.lastMessages.length).toBeLessThan(messages.length);
    expect(llm.invokeCount).toBe(1);
  });

  it("intercepts call method and packs messages", async () => {
    const llm = createMockLlm(["call"]);
    const wrapped = withContextCrewAI(llm, {
      budget: 200,
      reserveTokens: 0,
      log: false,
    });

    const messages = manyMessages(20);
    await wrapped.call!(messages);

    expect(llm.lastMessages.length).toBeLessThan(messages.length);
    expect(llm.callCount).toBe(1);
  });

  it("works with LangChain-style _getType messages", async () => {
    const llm = createMockLlm(["invoke"]);
    const wrapped = withContextCrewAI(llm, {
      budget: 100_000,
      log: false,
    });

    const messages = [
      { content: "system prompt", _getType: () => "system" },
      { content: "user msg", _getType: () => "human" },
      { content: "ai reply", _getType: () => "ai" },
    ];
    await wrapped.invoke!(messages);

    expect(llm.lastMessages).toHaveLength(3);
  });

  it("fires events with crewai framework name", async () => {
    const packListener = vi.fn();
    const llm = createMockLlm(["invoke"]);
    const wrapped = withContextCrewAI(llm, {
      budget: 200,
      reserveTokens: 0,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.invoke!(manyMessages(15));
    expect(packListener.mock.calls[0][0].framework).toBe("crewai");
  });

  it("extracts model name from model_name", async () => {
    const packListener = vi.fn();
    const llm = createMockLlm(["invoke"]);
    llm.model_name = "claude-3-haiku";

    const wrapped = withContextCrewAI(llm, {
      budget: 100_000,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.invoke!([{ role: "user", content: "hi" }]);
    expect(packListener.mock.calls[0][0].model).toBe("claude-3-haiku");
  });

  it("extracts model name from model property", async () => {
    const packListener = vi.fn();
    const llm: CrewAILike & { lastMessages: unknown[] } = {
      model: "gpt-4-turbo",
      lastMessages: [],
      async invoke(messages: unknown[]) {
        llm.lastMessages = messages;
        return { content: "ok" };
      },
    };

    const wrapped = withContextCrewAI(llm, {
      budget: 100_000,
      log: false,
      on: { pack: packListener },
    });

    await wrapped.invoke!([{ role: "user", content: "hi" }]);
    expect(packListener.mock.calls[0][0].model).toBe("gpt-4-turbo");
  });

  it("falls through on error", async () => {
    const llm = createMockLlm(["invoke"]);
    const errorListener = vi.fn();

    const wrapped = withContextCrewAI(llm, {
      budget: -1,
      reserveTokens: 0,
      log: false,
      on: { error: errorListener },
    });

    const result = await wrapped.invoke!(manyMessages(5));
    expect(result).toEqual({ content: "invoked" });
  });

  it("passes empty messages through without interception", async () => {
    const llm = createMockLlm(["invoke"]);
    const wrapped = withContextCrewAI(llm, {
      budget: 100_000,
      log: false,
    });

    await wrapped.invoke!([]);
    expect(llm.lastMessages).toHaveLength(0);
  });
});
