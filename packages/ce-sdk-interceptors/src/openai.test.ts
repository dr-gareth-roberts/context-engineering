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

/**
 * Mock of the OpenAI client whose `create()` returns an APIPromise-like object:
 * a real thenable (so `await` yields the body) that also carries the public
 * helper methods `.withResponse()` and `.asResponse()`, mirroring the real SDK.
 */
function createApiPromiseMockOpenAIClient() {
  const body = {
    id: "chatcmpl-123",
    choices: [{ message: { role: "assistant", content: "Hello!" } }],
  };
  const rawResponse = { headers: { "x-request-id": "req-abc" } };

  const createFn = vi.fn((..._args: unknown[]) => {
    // Build a fresh APIPromise-like per call: a thenable plus SDK helpers.
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
    chat: { completions: { create: createFn } },
    _createFn: createFn,
    _body: body,
    _rawResponse: rawResponse,
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

  describe("APIPromise helper forwarding", () => {
    it("awaiting the wrapped create() still yields the response body", async () => {
      const mock = createApiPromiseMockOpenAIClient();
      const client = withContext(mock, { log: false });

      const result = await client.chat.completions.create({
        model: "gpt-4o",
        messages: [{ role: "user", content: "Hello" }],
      });

      expect(result).toEqual(mock._body);
    });

    it("forwards .withResponse() through the packing layer", async () => {
      const mock = createApiPromiseMockOpenAIClient();
      const client = withContext(mock, { log: false });

      // Documented SDK pattern for reading response headers / request IDs.
      const { data, response } = await client.chat.completions
        .create({
          model: "gpt-4o",
          messages: [{ role: "user", content: "Hello" }],
        })
        .withResponse();

      expect(data).toEqual(mock._body);
      expect(response).toEqual(mock._rawResponse);
    });

    it("forwards .asResponse() through the packing layer", async () => {
      const mock = createApiPromiseMockOpenAIClient();
      const client = withContext(mock, { log: false });

      const response = await client.chat.completions
        .create({
          model: "gpt-4o",
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
        // Pre-attach a no-op catch so the raw mock promise itself does not warn;
        // the assertion below proves the shim forwards the rejection to the caller.
        apiPromise.catch(() => undefined);
        apiPromise.withResponse = () => Promise.reject(apiError);
        apiPromise.asResponse = () => Promise.reject(apiError);
        return apiPromise;
      });
      const mock = {
        chat: { completions: { create: rejectingCreate } },
      };
      const client = withContext(mock, { log: false });

      await expect(
        client.chat.completions
          .create({
            model: "gpt-4o",
            messages: [{ role: "user", content: "Hello" }],
          })
          .withResponse()
      ).rejects.toThrow("API 500");
    });

    it("still packs messages when .withResponse() is used", async () => {
      const mock = createApiPromiseMockOpenAIClient();
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

      await client.chat.completions
        .create({ model: "gpt-4o", messages: longMessages })
        .withResponse();

      const passedParams = mock._createFn.mock.calls[0][0] as Record<
        string,
        unknown
      >;
      const messages = passedParams.messages as Array<{ role: string }>;
      // Packing must still have run even though .withResponse() was awaited.
      expect(messages.length).toBeLessThan(longMessages.length);
      expect(messages[0].role).toBe("system");
    });
  });
});
