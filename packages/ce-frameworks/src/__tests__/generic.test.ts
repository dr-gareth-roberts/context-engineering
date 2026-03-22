import { describe, it, expect, vi } from "vitest";
import { withContextGeneric } from "../generic.js";
import type { GenericMessage } from "../types.js";

function createMockTarget() {
  const target = {
    modelId: "custom-model",
    lastArgs: [] as unknown[],
    async generate(...args: unknown[]) {
      target.lastArgs = args;
      return { output: "generated" };
    },
    async otherMethod() {
      return "other";
    },
  };
  return target;
}

function manyMessages(count: number): GenericMessage[] {
  const msgs: GenericMessage[] = [
    { role: "system", content: "You are helpful." },
  ];
  for (let i = 1; i < count; i++) {
    const role = i % 2 === 1 ? "user" : "assistant";
    msgs.push({ role, content: `Message ${i}: ${"word ".repeat(50).trim()}` });
  }
  return msgs;
}

describe("withContextGeneric", () => {
  it("intercepts the specified method and packs messages", async () => {
    const target = createMockTarget();
    const wrapped = withContextGeneric(target, "generate", {
      budget: 200,
      reserveTokens: 0,
      log: false,
      messageExtractor: args =>
        (args[0] as { messages: GenericMessage[] }).messages,
      messageInjector: (args, packed) => [
        { ...(args[0] as object), messages: packed },
      ],
    });

    const messages = manyMessages(20);
    await wrapped.generate({ messages });

    const passedArg = target.lastArgs[0] as { messages: GenericMessage[] };
    expect(passedArg.messages.length).toBeLessThan(messages.length);
  });

  it("passes through when under budget", async () => {
    const target = createMockTarget();
    const wrapped = withContextGeneric(target, "generate", {
      budget: 100_000,
      log: false,
      messageExtractor: args =>
        (args[0] as { messages: GenericMessage[] }).messages,
      messageInjector: (args, packed) => [
        { ...(args[0] as object), messages: packed },
      ],
    });

    const messages: GenericMessage[] = [{ role: "user", content: "Hi" }];
    await wrapped.generate({ messages });

    const passedArg = target.lastArgs[0] as { messages: GenericMessage[] };
    expect(passedArg.messages).toHaveLength(1);
  });

  it("supports custom model extractor", async () => {
    const packListener = vi.fn();
    const target = createMockTarget();
    const wrapped = withContextGeneric(target, "generate", {
      budget: 100_000,
      log: false,
      messageExtractor: args =>
        (args[0] as { messages: GenericMessage[] }).messages,
      messageInjector: (args, packed) => [
        { ...(args[0] as object), messages: packed },
      ],
      modelExtractor: t => (t as typeof target).modelId,
      on: { pack: packListener },
    });

    await wrapped.generate({ messages: [{ role: "user", content: "hi" }] });
    expect(packListener.mock.calls[0][0].model).toBe("custom-model");
  });

  it("supports custom framework name", async () => {
    const packListener = vi.fn();
    const target = createMockTarget();
    const wrapped = withContextGeneric(target, "generate", {
      budget: 100_000,
      log: false,
      messageExtractor: args =>
        (args[0] as { messages: GenericMessage[] }).messages,
      messageInjector: (args, packed) => [
        { ...(args[0] as object), messages: packed },
      ],
      frameworkName: "my-framework",
      on: { pack: packListener },
    });

    await wrapped.generate({ messages: [{ role: "user", content: "hi" }] });
    expect(packListener.mock.calls[0][0].framework).toBe("my-framework");
  });

  it("does not intercept other methods", async () => {
    const target = createMockTarget();
    const wrapped = withContextGeneric(target, "generate", {
      budget: 100_000,
      log: false,
      messageExtractor: args => args[0] as GenericMessage[],
      messageInjector: (args, packed) => [packed],
    });

    const result = await wrapped.otherMethod();
    expect(result).toBe("other");
  });

  it("falls through on error", async () => {
    const target = createMockTarget();
    const errorListener = vi.fn();

    const wrapped = withContextGeneric(target, "generate", {
      budget: -1,
      reserveTokens: 0,
      log: false,
      messageExtractor: args =>
        (args[0] as { messages: GenericMessage[] }).messages,
      messageInjector: (args, packed) => [
        { ...(args[0] as object), messages: packed },
      ],
      on: { error: errorListener },
    });

    const result = await wrapped.generate({
      messages: manyMessages(5),
    });
    expect(result).toEqual({ output: "generated" });
  });

  it("handles empty messages gracefully", async () => {
    const target = createMockTarget();
    const wrapped = withContextGeneric(target, "generate", {
      budget: 100_000,
      log: false,
      messageExtractor: args =>
        (args[0] as { messages: GenericMessage[] }).messages,
      messageInjector: (args, packed) => [
        { ...(args[0] as object), messages: packed },
      ],
    });

    await wrapped.generate({ messages: [] });
    const passedArg = target.lastArgs[0] as { messages: GenericMessage[] };
    expect(passedArg.messages).toHaveLength(0);
  });

  it("works with arbitrary method names", async () => {
    const target = {
      async customChat(messages: GenericMessage[]) {
        return { messages };
      },
    };

    const wrapped = withContextGeneric(target, "customChat", {
      budget: 100_000,
      log: false,
      messageExtractor: args => args[0] as GenericMessage[],
      messageInjector: (_, packed) => [packed],
    });

    const result = await (wrapped as typeof target).customChat([
      { role: "user", content: "hi" },
    ]);
    expect(result).toBeDefined();
  });
});
