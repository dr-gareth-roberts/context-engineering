import { describe, expect, it, vi } from "vitest";
import { OpenAIProvider, OpenAIEmbeddingProvider } from "./openai.js";
import { AnthropicProvider } from "./anthropic.js";
import { MODEL_METADATA } from "./models.js";
import { createLazyClient } from "./lazy-client.js";

/**
 * Inject a mock client into a provider that uses createLazyClient.
 * Replaces the private getClient function with one that resolves to the mock.
 */
function injectClient<T>(provider: unknown, mock: T): void {
  (provider as { getClient: () => Promise<T> }).getClient = () =>
    Promise.resolve(mock);
}

// ─── createLazyClient ─────────────────────────────────────────────────

describe("createLazyClient", () => {
  it("calls factory only once for multiple invocations", async () => {
    const factory = vi.fn().mockResolvedValue("client");
    const get = createLazyClient(factory);

    await get();
    await get();
    await get();

    expect(factory).toHaveBeenCalledTimes(1);
  });

  it("returns the same client instance each time", async () => {
    const client = { id: 1 };
    const get = createLazyClient(() => Promise.resolve(client));

    const a = await get();
    const b = await get();
    expect(a).toBe(b);
    expect(a).toBe(client);
  });

  it("deduplicates concurrent calls", async () => {
    let resolveFactory!: (value: string) => void;
    const factory = vi.fn(
      () =>
        new Promise<string>(resolve => {
          resolveFactory = resolve;
        })
    );

    const get = createLazyClient(factory);
    const p1 = get();
    const p2 = get();

    expect(factory).toHaveBeenCalledTimes(1);

    resolveFactory("client");
    const [r1, r2] = await Promise.all([p1, p2]);
    expect(r1).toBe("client");
    expect(r2).toBe("client");
  });

  it("clears cached rejection so next call retries", async () => {
    let callCount = 0;
    const factory = vi.fn(() => {
      callCount++;
      if (callCount === 1) return Promise.reject(new Error("fail"));
      return Promise.resolve("ok");
    });

    const get = createLazyClient(factory);

    await expect(get()).rejects.toThrow("fail");
    const result = await get();
    expect(result).toBe("ok");
    expect(factory).toHaveBeenCalledTimes(2);
  });
});

// ─── OpenAIProvider ───────────────────────────────────────────────────

describe("OpenAIProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(OpenAIProvider);
  });

  it("generate rejects empty messages", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    injectClient(provider, {});

    await expect(provider.generate([])).rejects.toThrow(
      "At least one message is required"
    );
  });

  it("generate returns text and model from response", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });

    injectClient(provider, {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [{ message: { content: "Hello from GPT" } }],
            model: "gpt-4o-mini",
            usage: {
              prompt_tokens: 10,
              completion_tokens: 5,
              total_tokens: 15,
            },
          }),
        },
      },
    });

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("Hello from GPT");
    expect(result.model).toBe("gpt-4o-mini");
    expect(result.usage).toEqual({
      inputTokens: 10,
      outputTokens: 5,
      totalTokens: 15,
    });
  });

  it("generate passes max_tokens for non-reasoning models", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok" } }],
      model: "gpt-4o",
      usage: null,
    });

    injectClient(provider, {
      chat: { completions: { create: createMock } },
    });

    await provider.generate(
      [
        { role: "system", content: "Be helpful" },
        { role: "user", content: "Hi" },
      ],
      { model: "gpt-4o", maxTokens: 200, temperature: 0.5 }
    );

    expect(createMock).toHaveBeenCalledWith({
      model: "gpt-4o",
      messages: [
        { role: "system", content: "Be helpful" },
        { role: "user", content: "Hi" },
      ],
      max_tokens: 200,
      temperature: 0.5,
    });
  });

  it("generate uses max_tokens for non-reasoning models like gpt-4.1", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok" } }],
      model: "gpt-4.1",
      usage: null,
    });

    injectClient(provider, {
      chat: { completions: { create: createMock } },
    });

    await provider.generate([{ role: "user", content: "Hi" }], {
      model: "gpt-4.1",
      maxTokens: 200,
    });

    expect(createMock).toHaveBeenCalledWith({
      model: "gpt-4.1",
      messages: [{ role: "user", content: "Hi" }],
      max_tokens: 200,
    });
  });

  it("generate uses max_completion_tokens for o-series models", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok" } }],
      model: "o3",
      usage: null,
    });

    injectClient(provider, {
      chat: { completions: { create: createMock } },
    });

    await provider.generate([{ role: "user", content: "Hi" }], {
      model: "o3",
      maxTokens: 500,
    });

    expect(createMock).toHaveBeenCalledWith({
      model: "o3",
      messages: [{ role: "user", content: "Hi" }],
      max_completion_tokens: 500,
    });
  });

  it("generate omits temperature when not provided", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok" } }],
      model: "gpt-4o-mini",
      usage: null,
    });

    injectClient(provider, {
      chat: { completions: { create: createMock } },
    });

    await provider.generate([{ role: "user", content: "Hi" }]);

    const calledWith = createMock.mock.calls[0][0];
    expect(calledWith).not.toHaveProperty("temperature");
    expect(calledWith).not.toHaveProperty("max_tokens");
    expect(calledWith).not.toHaveProperty("max_completion_tokens");
  });

  it("generate handles empty choices", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    injectClient(provider, {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [],
            model: "gpt-4o-mini",
          }),
        },
      },
    });

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("");
  });

  it("generate handles missing usage", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    injectClient(provider, {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [{ message: { content: "text" } }],
            model: "gpt-4o-mini",
          }),
        },
      },
    });

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.usage).toBeUndefined();
  });

  it("generate propagates API errors", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    injectClient(provider, {
      chat: {
        completions: {
          create: vi.fn().mockRejectedValue(new Error("Rate limited")),
        },
      },
    });

    await expect(
      provider.generate([{ role: "user", content: "Hi" }])
    ).rejects.toThrow("Rate limited");
  });
});

// ─── AnthropicProvider ────────────────────────────────────────────────

describe("AnthropicProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(AnthropicProvider);
  });

  it("generate rejects empty messages", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    injectClient(provider, {});

    await expect(provider.generate([])).rejects.toThrow(
      "At least one message is required"
    );
  });

  it("generate rejects unsupported message roles", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    injectClient(provider, {
      messages: { create: vi.fn() },
    });

    await expect(
      provider.generate([
        { role: "user", content: "Hi" },
        { role: "tool", content: "result" },
      ])
    ).rejects.toThrow('Unsupported message role "tool" for the Anthropic API');
  });

  it("generate rejects all-system messages", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    injectClient(provider, {
      messages: { create: vi.fn() },
    });

    await expect(
      provider.generate([{ role: "system", content: "Instructions only" }])
    ).rejects.toThrow("At least one non-system message is required");
  });

  it("generate returns text from content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    injectClient(provider, {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Hello from Claude" }],
          model: "claude-sonnet-4-6",
          usage: {
            input_tokens: 12,
            output_tokens: 8,
          },
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("Hello from Claude");
    expect(result.model).toBe("claude-sonnet-4-6");
    expect(result.usage).toEqual({
      inputTokens: 12,
      outputTokens: 8,
      totalTokens: 20,
    });
  });

  it("generate extracts system messages and passes to system param", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      content: [{ type: "text", text: "ok" }],
      model: "claude-sonnet-4-6",
      usage: { input_tokens: 10, output_tokens: 2 },
    });

    injectClient(provider, { messages: { create: createMock } });

    await provider.generate([
      { role: "system", content: "You are a helpful assistant." },
      { role: "user", content: "Hi" },
    ]);

    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({
        system: "You are a helpful assistant.",
        messages: [{ role: "user", content: "Hi" }],
      })
    );
  });

  it("generate joins multiple system messages", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      content: [{ type: "text", text: "ok" }],
      model: "claude-sonnet-4-6",
      usage: { input_tokens: 10, output_tokens: 2 },
    });

    injectClient(provider, { messages: { create: createMock } });

    await provider.generate([
      { role: "system", content: "First instruction." },
      { role: "system", content: "Second instruction." },
      { role: "user", content: "Hi" },
    ]);

    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({
        system: "First instruction.\n\nSecond instruction.",
      })
    );
  });

  it("generate omits system param when no system messages", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      content: [{ type: "text", text: "ok" }],
      model: "claude-sonnet-4-6",
      usage: { input_tokens: 5, output_tokens: 1 },
    });

    injectClient(provider, { messages: { create: createMock } });

    await provider.generate([{ role: "user", content: "Hi" }]);

    const calledWith = createMock.mock.calls[0][0];
    expect(calledWith).not.toHaveProperty("system");
  });

  it("generate omits temperature when not provided", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      content: [{ type: "text", text: "ok" }],
      model: "claude-sonnet-4-6",
      usage: { input_tokens: 5, output_tokens: 1 },
    });

    injectClient(provider, { messages: { create: createMock } });

    await provider.generate([{ role: "user", content: "Hi" }]);

    const calledWith = createMock.mock.calls[0][0];
    expect(calledWith).not.toHaveProperty("temperature");
  });

  it("generate joins multiple text content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    injectClient(provider, {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [
            { type: "text", text: "Part 1" },
            { type: "text", text: "Part 2" },
          ],
          model: "claude-sonnet-4-6",
          usage: { input_tokens: 10, output_tokens: 5 },
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("Part 1Part 2");
  });

  it("generate handles non-text content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    injectClient(provider, {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [
            { type: "tool_use", id: "tool-1", name: "search", input: {} },
          ],
          model: "claude-sonnet-4-6",
          usage: { input_tokens: 10, output_tokens: 5 },
        }),
      },
    });

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("");
  });

  it("generate passes custom model and options", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      content: [{ type: "text", text: "ok" }],
      model: "claude-opus-4-6",
      usage: { input_tokens: 5, output_tokens: 1 },
    });

    injectClient(provider, { messages: { create: createMock } });

    await provider.generate([{ role: "user", content: "Hi" }], {
      model: "claude-opus-4-6",
      maxTokens: 4096,
      temperature: 0.7,
    });

    expect(createMock).toHaveBeenCalledWith({
      model: "claude-opus-4-6",
      max_tokens: 4096,
      temperature: 0.7,
      messages: [{ role: "user", content: "Hi" }],
    });
  });

  it("generate propagates API errors", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    injectClient(provider, {
      messages: {
        create: vi.fn().mockRejectedValue(new Error("Auth failed")),
      },
    });

    await expect(
      provider.generate([{ role: "user", content: "Hi" }])
    ).rejects.toThrow("Auth failed");
  });
});

// ─── OpenAIEmbeddingProvider ──────────────────────────────────────────

describe("OpenAIEmbeddingProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(OpenAIEmbeddingProvider);
  });

  it("embed returns vectors from response", async () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });

    injectClient(provider, {
      embeddings: {
        create: vi.fn().mockResolvedValue({
          data: [
            { embedding: [0.1, 0.2, 0.3] },
            { embedding: [0.4, 0.5, 0.6] },
          ],
          model: "text-embedding-3-small",
        }),
      },
    });

    const result = await provider.embed(["hello", "world"]);

    expect(result.vectors).toEqual([
      [0.1, 0.2, 0.3],
      [0.4, 0.5, 0.6],
    ]);
    expect(result.model).toBe("text-embedding-3-small");
  });

  it("embed handles string input (wraps as array)", async () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      data: [{ embedding: [0.1, 0.2] }],
      model: "text-embedding-3-small",
    });

    injectClient(provider, { embeddings: { create: createMock } });

    await provider.embed("hello");

    expect(createMock).toHaveBeenCalledWith({
      model: "text-embedding-3-small",
      input: ["hello"],
    });
  });

  it("embed passes custom model", async () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      data: [{ embedding: [0.1] }],
      model: "text-embedding-3-large",
    });

    injectClient(provider, { embeddings: { create: createMock } });

    await provider.embed("hello", { model: "text-embedding-3-large" });

    expect(createMock).toHaveBeenCalledWith({
      model: "text-embedding-3-large",
      input: ["hello"],
    });
  });

  it("embed propagates API errors", async () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });
    injectClient(provider, {
      embeddings: {
        create: vi.fn().mockRejectedValue(new Error("Quota exceeded")),
      },
    });

    await expect(provider.embed("hello")).rejects.toThrow("Quota exceeded");
  });
});

// ─── MODEL_METADATA ───────────────────────────────────────────────────

describe("MODEL_METADATA", () => {
  it("is a non-empty object", () => {
    expect(typeof MODEL_METADATA).toBe("object");
    expect(Object.keys(MODEL_METADATA).length).toBeGreaterThan(0);
  });

  it("contains openai provider", () => {
    expect(MODEL_METADATA).toHaveProperty("openai");
  });

  it("contains anthropic provider", () => {
    expect(MODEL_METADATA).toHaveProperty("anthropic");
  });

  it("includes gpt-4o in openai models", () => {
    expect(MODEL_METADATA.openai).toHaveProperty("gpt-4o");
  });

  it("includes claude-3-5-sonnet-20241022 in anthropic models", () => {
    expect(MODEL_METADATA.anthropic).toHaveProperty(
      "claude-3-5-sonnet-20241022"
    );
  });

  it("model entries have maxTokens", () => {
    expect(MODEL_METADATA.openai["gpt-4o"].maxTokens).toBe(128000);
    expect(
      MODEL_METADATA.anthropic["claude-3-5-sonnet-20241022"].maxTokens
    ).toBe(200000);
  });

  it("has claude-haiku-4-5 key aligned with cost.ts MODEL_PRICING", () => {
    expect(MODEL_METADATA.anthropic).toHaveProperty("claude-haiku-4-5");
  });
});
