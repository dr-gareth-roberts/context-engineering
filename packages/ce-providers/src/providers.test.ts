import { describe, expect, it } from "vitest";
import { OpenAIProvider, OpenAIEmbeddingProvider } from "./openai.js";
import { AnthropicProvider } from "./anthropic.js";
import { MODEL_METADATA } from "./models.js";

describe("OpenAIProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new OpenAIProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(OpenAIProvider);
  });
});

describe("AnthropicProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new AnthropicProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(AnthropicProvider);
  });
});

describe("OpenAIEmbeddingProvider", () => {
  it("accepts apiKey option", () => {
    const provider = new OpenAIEmbeddingProvider({ apiKey: "test-key" });
    expect(provider).toBeInstanceOf(OpenAIEmbeddingProvider);
  });
});

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
