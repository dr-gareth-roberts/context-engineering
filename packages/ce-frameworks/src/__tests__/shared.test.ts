import { describe, it, expect, vi } from "vitest";
import {
  packMessages,
  extractText,
  messagesToContextItems,
  contextItemsToMessages,
} from "../shared.js";
import type { GenericMessage, ResolvedConfig, ContextEvent } from "../types.js";
import { resolveConfig } from "../types.js";

function makeMessages(count: number, tokensPer = 100): GenericMessage[] {
  return Array.from({ length: count }, (_, i) => ({
    role: i === 0 ? "system" : i % 2 === 1 ? "user" : "assistant",
    content: "word ".repeat(tokensPer).trim(),
  }));
}

describe("extractText", () => {
  it("handles string content", () => {
    expect(extractText("hello")).toBe("hello");
  });

  it("handles structured content arrays", () => {
    const content = [
      { type: "text", text: "hello" },
      { type: "image", url: "http://example.com" },
      { type: "text", text: "world" },
    ];
    expect(extractText(content)).toBe("hello\nworld");
  });

  it("handles object content via JSON.stringify", () => {
    expect(extractText({ key: "value" })).toBe('{"key":"value"}');
  });

  it("handles null/undefined", () => {
    expect(extractText(null)).toBe("");
    expect(extractText(undefined)).toBe("");
  });
});

describe("messagesToContextItems", () => {
  it("converts messages with correct roles and priorities", () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "You are helpful" },
      { role: "user", content: "Hello" },
      { role: "assistant", content: "Hi there" },
      { role: "user", content: "How are you?" },
    ];
    const config = resolveConfig({ budget: 100_000 });
    const items = messagesToContextItems(messages, config);

    expect(items).toHaveLength(4);
    expect(items[0].kind).toBe("system");
    expect(items[0].priority).toBe(100);
    // Last 2 should be protected (priority 90)
    expect(items[2].priority).toBe(90);
    expect(items[3].priority).toBe(90);
  });

  it("sets recency from 0 to 1", () => {
    const messages = makeMessages(5);
    const config = resolveConfig();
    const items = messagesToContextItems(messages, config);

    expect(items[0].recency).toBe(0);
    expect(items[4].recency).toBe(1);
  });

  it("preserves original message in metadata", () => {
    const messages: GenericMessage[] = [
      { role: "user", content: "test", extra: "data" },
    ];
    const config = resolveConfig();
    const items = messagesToContextItems(messages, config);

    expect(items[0].metadata?.originalMessage).toBe(messages[0]);
    expect(items[0].metadata?.originalIndex).toBe(0);
  });
});

describe("contextItemsToMessages", () => {
  it("reconstructs messages in original order", () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "system" },
      { role: "user", content: "first" },
      { role: "user", content: "second" },
    ];
    const config = resolveConfig();
    const items = messagesToContextItems(messages, config);

    // Simulate keeping only first and last
    const kept = [items[0], items[2]];
    const result = contextItemsToMessages(messages, kept);

    expect(result).toHaveLength(2);
    expect(result[0].role).toBe("system");
    expect(result[1].content).toBe("second");
  });

  it("injects summary before first non-system message", () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "system" },
      { role: "user", content: "latest" },
    ];
    const config = resolveConfig();
    const items = messagesToContextItems(messages, config);

    const result = contextItemsToMessages(
      messages,
      items,
      "Summary of dropped messages"
    );

    expect(result).toHaveLength(3);
    expect(result[0].role).toBe("system");
    expect(result[1].role).toBe("system");
    expect(result[1].content).toContain("Context summary");
    expect(result[2].content).toBe("latest");
  });
});

describe("packMessages", () => {
  it("passes through messages that fit within budget", async () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "Be helpful" },
      { role: "user", content: "Hi" },
    ];
    const config = resolveConfig({ budget: 100_000, log: false });

    const { packed, event } = await packMessages(
      messages,
      "gpt-4o",
      "test",
      config
    );

    expect(packed).toBe(messages); // Same reference — no change
    expect(event.trimmedMessages).toBe(0);
    expect(event.framework).toBe("test");
    expect(event.model).toBe("gpt-4o");
  });

  it("trims messages when over budget", async () => {
    // Create enough messages to exceed a tiny budget
    const messages = makeMessages(20, 50);
    const config = resolveConfig({ budget: 200, reserveTokens: 0, log: false });

    const { packed, event } = await packMessages(
      messages,
      "gpt-4o",
      "test",
      config
    );

    expect(packed.length).toBeLessThan(messages.length);
    expect(event.trimmedMessages).toBeGreaterThan(0);
    expect(event.keptMessages).toBe(packed.length);
  });

  it("protects system and recent messages when trimming", async () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "System prompt " + "word ".repeat(10) },
      { role: "user", content: "old message " + "word ".repeat(50) },
      { role: "assistant", content: "old reply " + "word ".repeat(50) },
      { role: "user", content: "recent question " + "word ".repeat(10) },
      { role: "assistant", content: "recent answer " + "word ".repeat(10) },
    ];

    const config = resolveConfig({
      budget: 100,
      reserveTokens: 0,
      recentMessageCount: 2,
      log: false,
    });

    const { packed } = await packMessages(messages, "gpt-4o", "test", config);

    const roles = packed.map(m => m.role);
    const contents = packed.map(m => m.content);

    // System and recent messages should be kept
    expect(contents.some(c => c.startsWith("System prompt"))).toBe(true);
    expect(contents.some(c => c.startsWith("recent question"))).toBe(true);
    expect(contents.some(c => c.startsWith("recent answer"))).toBe(true);
  });

  it("applies summarize strategy", async () => {
    const messages = makeMessages(20, 50);
    const config = resolveConfig({
      budget: 200,
      reserveTokens: 0,
      strategy: "summarize",
      log: false,
    });

    const { packed, event } = await packMessages(
      messages,
      "gpt-4o",
      "test",
      config
    );

    expect(event.summarized).toBe(true);
    // Should contain a summary message
    const summaryMsg = packed.find(m => m.content.includes("Context summary"));
    expect(summaryMsg).toBeDefined();
  });

  it("applies custom summarize function", async () => {
    const messages = makeMessages(20, 50);
    const customSummarizer = vi.fn().mockResolvedValue("Custom summary text");

    const config = resolveConfig({
      budget: 200,
      reserveTokens: 0,
      strategy: customSummarizer,
      log: false,
    });

    const { packed, event } = await packMessages(
      messages,
      "gpt-4o",
      "test",
      config
    );

    expect(event.summarized).toBe(true);
    expect(customSummarizer).toHaveBeenCalled();
    const summaryMsg = packed.find(m =>
      m.content.includes("Custom summary text")
    );
    expect(summaryMsg).toBeDefined();
  });

  it("emits correct ContextEvent", async () => {
    const messages = makeMessages(10, 50);
    const packListener = vi.fn();
    const trimListener = vi.fn();

    const config = resolveConfig({
      budget: 200,
      reserveTokens: 0,
      log: false,
      on: { pack: packListener, trim: trimListener },
    });

    await packMessages(messages, "gpt-4o", "langchain", config);

    expect(packListener).toHaveBeenCalledTimes(1);
    const event: ContextEvent = packListener.mock.calls[0][0];
    expect(event.framework).toBe("langchain");
    expect(event.model).toBe("gpt-4o");
    expect(event.totalMessages).toBe(10);
    expect(event.utilization).toBeGreaterThan(0);
    expect(event.packTimeMs).toBeGreaterThanOrEqual(0);

    // Should also fire trim since messages were trimmed
    expect(trimListener).toHaveBeenCalledTimes(1);
  });

  it("records to recorder when attached", async () => {
    const messages = makeMessages(20, 50);
    const recorder = { record: vi.fn() };

    const config = resolveConfig({
      budget: 200,
      reserveTokens: 0,
      log: false,
      recorder:
        recorder as unknown as import("@context-engineering/core").ContextRecorder,
    });

    await packMessages(messages, "gpt-4o", "test", config);

    expect(recorder.record).toHaveBeenCalledTimes(1);
    const recording = recorder.record.mock.calls[0][0];
    expect(recording.model).toBe("gpt-4o");
    expect(recording.metadata.framework).toBe("test");
  });

  it("logs to console when log is true", async () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const messages: GenericMessage[] = [{ role: "user", content: "Hi" }];
    const config = resolveConfig({ budget: 100_000, log: true });

    await packMessages(messages, "gpt-4o", "langchain", config);

    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("[context-engineering]")
    );
    consoleSpy.mockRestore();
  });
});
