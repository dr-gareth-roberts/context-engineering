import { describe, it, expect, vi } from "vitest";
import { createLLMSummarizer } from "./summarizer.js";

describe("createLLMSummarizer", () => {
  it("returns summarized content from provider", async () => {
    const mockProvider = {
      generate: vi.fn().mockResolvedValue({
        text: "Concise summary of the conversation.",
        model: "mock",
        usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
      }),
    };
    const summarizer = createLLMSummarizer({ provider: mockProvider as any });
    const item = {
      id: "batch1",
      content:
        "Long conversation content about various topics discussed at length",
      tokens: 500,
    };
    const result = await summarizer(item, 50);
    expect(result).not.toBeNull();
    expect(result!.content).toBe("Concise summary of the conversation.");
    expect(result!.id).toBe("batch1");
    expect(mockProvider.generate).toHaveBeenCalled();
  });

  it("returns null on provider error", async () => {
    const mockProvider = {
      generate: vi.fn().mockRejectedValue(new Error("API error")),
    };
    const summarizer = createLLMSummarizer({ provider: mockProvider as any });
    const result = await summarizer({ id: "x", content: "text" }, 50);
    expect(result).toBeNull();
  });

  it("uses custom prompt when provided", async () => {
    const mockProvider = {
      generate: vi.fn().mockResolvedValue({
        text: "Custom summary",
        model: "mock",
        usage: { inputTokens: 50, outputTokens: 10, totalTokens: 60 },
      }),
    };
    const summarizer = createLLMSummarizer({
      provider: mockProvider as any,
      prompt: "Summarize in bullet points:",
    });
    await summarizer({ id: "y", content: "text" }, 50);
    const callArgs = mockProvider.generate.mock.calls[0];
    expect(
      callArgs[0].some((m: any) => m.content.includes("bullet points"))
    ).toBe(true);
  });

  it("passes maxOutputTokens to provider", async () => {
    const mockProvider = {
      generate: vi.fn().mockResolvedValue({
        text: "Short",
        model: "mock",
        usage: { inputTokens: 50, outputTokens: 5, totalTokens: 55 },
      }),
    };
    const summarizer = createLLMSummarizer({
      provider: mockProvider as any,
      maxOutputTokens: 100,
    });
    await summarizer({ id: "z", content: "text" }, 50);
    const callArgs = mockProvider.generate.mock.calls[0];
    expect(callArgs[1].maxTokens).toBe(100);
  });

  it("estimates tokens on returned item", async () => {
    const mockProvider = {
      generate: vi.fn().mockResolvedValue({
        text: "A short summary",
        model: "mock",
        usage: { inputTokens: 50, outputTokens: 3, totalTokens: 53 },
      }),
    };
    const summarizer = createLLMSummarizer({ provider: mockProvider as any });
    const result = await summarizer(
      { id: "w", content: "original long text" },
      50
    );
    expect(result).not.toBeNull();
    expect(result!.tokens).toBeGreaterThan(0);
  });

  it("calls onError callback when provider throws", async () => {
    const apiError = new Error("API rate limit exceeded");
    const mockProvider = {
      generate: vi.fn().mockRejectedValue(apiError),
    };
    const onError = vi.fn();
    const summarizer = createLLMSummarizer({
      provider: mockProvider as any,
      onError,
    });
    const result = await summarizer({ id: "err", content: "text" }, 50);
    expect(result).toBeNull();
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(apiError);
  });
});
