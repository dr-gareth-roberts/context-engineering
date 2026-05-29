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

/**
 * Mock of the Anthropic client whose `create()` returns an APIPromise-like
 * object: a real thenable (so `await` yields the body) that also carries the
 * public helper methods `.withResponse()` and `.asResponse()`.
 */
function createApiPromiseMockAnthropicClient() {
  const body = {
    id: "msg_123",
    content: [{ type: "text", text: "Hello!" }],
    role: "assistant",
  };
  const rawResponse = { headers: { "request-id": "req-xyz" } };

  const createFn = vi.fn((..._args: unknown[]) => {
    const apiPromise = Promise.resolve(body) as Promise<typeof body> & {
      withResponse: () => Promise<{
        data: typeof body;
        response: typeof rawResponse;
      }>;
      asResponse: () => Promise<typeof rawResponse>;
    };
    apiPromise.withResponse = () =>
      Promise.resolve({ data: body, response: rawResponse });
    apiPromise.asResponse = () => Promise.resolve(rawResponse);
    return apiPromise;
  });

  return {
    messages: { create: createFn },
    _createFn: createFn,
    _body: body,
    _rawResponse: rawResponse,
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
      messages: [{ role: "user", content: "Hello" }],
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
      messages: [{ role: "user", content: "Write me a function" }],
    });

    const passedParams = mock._createFn.mock.calls[0][0] as Record<
      string,
      unknown
    >;
    expect(passedParams.system).toBe("You are a coding assistant");
    const messages = passedParams.messages as Array<{ role: string }>;
    // System should not appear in messages array
    expect(messages.every(m => m.role !== "system")).toBe(true);
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

    const passedParams = mock._createFn.mock.calls[0][0] as Record<
      string,
      unknown
    >;
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

  it("folds an injected summary into the system param when no system prompt is set", async () => {
    const mock = createMockAnthropicClient();
    const client = withContextAnthropic(mock, {
      budget: 100,
      reserveTokens: 10,
      strategy: "summarize",
      log: false,
    });

    // Enough messages to overflow the budget so the summarize strategy runs
    // and injects a synthetic system message. No top-level `system` is passed.
    const longMessages = Array.from({ length: 20 }, (_, i) => ({
      role: (i % 2 === 0 ? "user" : "assistant") as "user" | "assistant",
      content: `This is message number ${i} with enough words to consume several tokens`,
    }));

    await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 1024,
      messages: longMessages,
    });

    const passedParams = mock._createFn.mock.calls[0][0] as Record<
      string,
      unknown
    >;
    const messages = passedParams.messages as Array<{ role: string }>;
    // Anthropic forbids role:"system" inside the messages array.
    expect(messages.every(m => m.role !== "system")).toBe(true);
    // The injected summary must be promoted to the top-level system param.
    expect(typeof passedParams.system).toBe("string");
    expect(passedParams.system as string).toContain("[Context summary");
  });

  describe("APIPromise helper forwarding", () => {
    it("awaiting the wrapped create() still yields the response body", async () => {
      const mock = createApiPromiseMockAnthropicClient();
      const client = withContextAnthropic(mock, { log: false });

      const result = await client.messages.create({
        model: "claude-sonnet-4-6",
        max_tokens: 1024,
        system: "You are helpful",
        messages: [{ role: "user", content: "Hello" }],
      });

      expect(result).toEqual(mock._body);
    });

    it("forwards .withResponse() through the packing layer", async () => {
      const mock = createApiPromiseMockAnthropicClient();
      const client = withContextAnthropic(mock, { log: false });

      const { data, response } = await client.messages
        .create({
          model: "claude-sonnet-4-6",
          max_tokens: 1024,
          system: "You are helpful",
          messages: [{ role: "user", content: "Hello" }],
        })
        .withResponse();

      expect(data).toEqual(mock._body);
      expect(response).toEqual(mock._rawResponse);
    });

    it("forwards .asResponse() through the packing layer", async () => {
      const mock = createApiPromiseMockAnthropicClient();
      const client = withContextAnthropic(mock, { log: false });

      const response = await client.messages
        .create({
          model: "claude-sonnet-4-6",
          max_tokens: 1024,
          messages: [{ role: "user", content: "Hello" }],
        })
        .asResponse();

      expect(response).toEqual(mock._rawResponse);
    });

    it("rejects from .withResponse() when the underlying API call rejects, without leaking an unhandled rejection", async () => {
      const apiError = new Error("API 500");
      const rejectingCreate = vi.fn(() => {
        const apiPromise = Promise.reject(apiError) as Promise<never> & {
          withResponse: () => Promise<never>;
          asResponse: () => Promise<never>;
        };
        apiPromise.catch(() => undefined);
        apiPromise.withResponse = () => Promise.reject(apiError);
        apiPromise.asResponse = () => Promise.reject(apiError);
        return apiPromise;
      });
      const mock = {
        messages: { create: rejectingCreate },
      };
      const client = withContextAnthropic(mock, { log: false });

      await expect(
        client.messages
          .create({
            model: "claude-sonnet-4-6",
            max_tokens: 1024,
            system: "You are helpful",
            messages: [{ role: "user", content: "Hello" }],
          })
          .withResponse()
      ).rejects.toThrow("API 500");
    });

    it("still packs messages when .withResponse() is used", async () => {
      const mock = createApiPromiseMockAnthropicClient();
      const client = withContextAnthropic(mock, {
        budget: 100,
        reserveTokens: 10,
        log: false,
      });

      const longMessages = Array.from({ length: 20 }, (_, i) => ({
        role: (i % 2 === 0 ? "user" : "assistant") as "user" | "assistant",
        content: `This is message number ${i} with enough words to consume several tokens`,
      }));

      await client.messages
        .create({
          model: "claude-sonnet-4-6",
          max_tokens: 1024,
          system: "You are helpful",
          messages: longMessages,
        })
        .withResponse();

      const passedParams = mock._createFn.mock.calls[0][0] as Record<
        string,
        unknown
      >;
      const messages = passedParams.messages as Array<{ role: string }>;
      // Packing must still have run even though .withResponse() was awaited.
      expect(messages.length).toBeLessThan(longMessages.length);
    });
  });
});
