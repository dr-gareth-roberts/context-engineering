import { describe, expect, it, vi } from "vitest";
import { OpenAIProvider, OpenAIEmbeddingProvider } from "./openai.js";
import { AnthropicProvider } from "./anthropic.js";
import { MODEL_METADATA } from "./models.js";

// ─── OpenAIProvider ───────────────────────────────────────────────────

describe("OpenAIProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(OpenAIProvider);
  });

  it("generate returns text and model from response", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });

    // Mock the internal client
    (provider as any).client = {
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
    };

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("Hello from GPT");
    expect(result.model).toBe("gpt-4o-mini");
    expect(result.usage).toEqual({
      inputTokens: 10,
      outputTokens: 5,
      totalTokens: 15,
    });
  });

  it("generate passes options to client", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    const createMock = vi.fn().mockResolvedValue({
      choices: [{ message: { content: "ok" } }],
      model: "gpt-4.1",
      usage: null,
    });

    (provider as any).client = {
      chat: { completions: { create: createMock } },
    };

    await provider.generate(
      [
        { role: "system", content: "Be helpful" },
        { role: "user", content: "Hi" },
      ],
      { model: "gpt-4.1", maxTokens: 200, temperature: 0.5 }
    );

    expect(createMock).toHaveBeenCalledWith({
      model: "gpt-4.1",
      messages: [
        { role: "system", content: "Be helpful" },
        { role: "user", content: "Hi" },
      ],
      max_tokens: 200,
      temperature: 0.5,
    });
  });

  it("generate handles empty choices", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    (provider as any).client = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [],
            model: "gpt-4o-mini",
          }),
        },
      },
    };

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("");
  });

  it("generate handles missing usage", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    (provider as any).client = {
      chat: {
        completions: {
          create: vi.fn().mockResolvedValue({
            choices: [{ message: { content: "text" } }],
            model: "gpt-4o-mini",
          }),
        },
      },
    };

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.usage).toBeUndefined();
  });

  it("generate propagates API errors", async () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    (provider as any).client = {
      chat: {
        completions: {
          create: vi.fn().mockRejectedValue(new Error("Rate limited")),
        },
      },
    };

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

  it("generate returns text from content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    (provider as any).client = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [{ type: "text", text: "Hello from Claude" }],
          model: "claude-3-5-sonnet-20241022",
          usage: {
            input_tokens: 12,
            output_tokens: 8,
          },
        }),
      },
    };

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("Hello from Claude");
    expect(result.model).toBe("claude-3-5-sonnet-20241022");
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
      model: "claude-3-5-sonnet-20241022",
      usage: { input_tokens: 10, output_tokens: 2 },
    });

    (provider as any).client = { messages: { create: createMock } };

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
      model: "claude-3-5-sonnet-20241022",
      usage: { input_tokens: 10, output_tokens: 2 },
    });

    (provider as any).client = { messages: { create: createMock } };

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
      model: "claude-3-5-sonnet-20241022",
      usage: { input_tokens: 5, output_tokens: 1 },
    });

    (provider as any).client = { messages: { create: createMock } };

    await provider.generate([{ role: "user", content: "Hi" }]);

    expect(createMock).toHaveBeenCalledWith(
      expect.objectContaining({
        system: undefined,
      })
    );
  });

  it("generate joins multiple text content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    (provider as any).client = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [
            { type: "text", text: "Part 1" },
            { type: "text", text: "Part 2" },
          ],
          model: "claude-3-5-sonnet-20241022",
          usage: { input_tokens: 10, output_tokens: 5 },
        }),
      },
    };

    const result = await provider.generate([{ role: "user", content: "Hi" }]);

    expect(result.text).toBe("Part 1Part 2");
  });

  it("generate handles non-text content blocks", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });

    (provider as any).client = {
      messages: {
        create: vi.fn().mockResolvedValue({
          content: [
            { type: "tool_use", id: "tool-1", name: "search", input: {} },
          ],
          model: "claude-3-5-sonnet-20241022",
          usage: { input_tokens: 10, output_tokens: 5 },
        }),
      },
    };

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

    (provider as any).client = { messages: { create: createMock } };

    await provider.generate([{ role: "user", content: "Hi" }], {
      model: "claude-opus-4-6",
      maxTokens: 4096,
      temperature: 0.7,
    });

    expect(createMock).toHaveBeenCalledWith({
      model: "claude-opus-4-6",
      max_tokens: 4096,
      temperature: 0.7,
      system: undefined,
      messages: [{ role: "user", content: "Hi" }],
    });
  });

  it("generate propagates API errors", async () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    (provider as any).client = {
      messages: {
        create: vi.fn().mockRejectedValue(new Error("Auth failed")),
      },
    };

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

    (provider as any).client = {
      embeddings: {
        create: vi.fn().mockResolvedValue({
          data: [
            { embedding: [0.1, 0.2, 0.3] },
            { embedding: [0.4, 0.5, 0.6] },
          ],
          model: "text-embedding-3-small",
        }),
      },
    };

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

    (provider as any).client = { embeddings: { create: createMock } };

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

    (provider as any).client = { embeddings: { create: createMock } };

    await provider.embed("hello", { model: "text-embedding-3-large" });

    expect(createMock).toHaveBeenCalledWith({
      model: "text-embedding-3-large",
      input: ["hello"],
    });
  });

  it("embed propagates API errors", async () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });
    (provider as any).client = {
      embeddings: {
        create: vi.fn().mockRejectedValue(new Error("Quota exceeded")),
      },
    };

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
});
