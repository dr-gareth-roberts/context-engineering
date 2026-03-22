import { describe, it, expect } from "vitest";
import {
  extractText,
  messagesToContextItems,
  contextItemsToMessages,
  type GenericMessage,
} from "./message-converter.js";
import { resolveConfig } from "./types.js";

describe("extractText", () => {
  it("extracts from a plain string", () => {
    expect(extractText("hello world")).toBe("hello world");
  });

  it("extracts from an array of content blocks", () => {
    const content = [
      { type: "text", text: "first" },
      { type: "image", url: "http://example.com/img.png" },
      { type: "text", text: "second" },
    ];
    expect(extractText(content)).toBe("first\nsecond");
  });

  it("handles empty content blocks", () => {
    expect(extractText([])).toBe("");
  });

  it("handles null-ish content", () => {
    expect(extractText(null as unknown as string)).toBe("");
  });
});

describe("messagesToContextItems", () => {
  const config = resolveConfig({ recentMessageCount: 2, systemPriority: 100 });

  it("assigns highest priority to system messages", () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "You are helpful" },
      { role: "user", content: "Hello" },
    ];
    const items = messagesToContextItems(messages, config);
    expect(items[0].priority).toBe(100);
    expect(items[0].kind).toBe("system");
  });

  it("protects recent messages with high priority", () => {
    const messages: GenericMessage[] = [
      { role: "system", content: "sys" },
      { role: "user", content: "old message 1" },
      { role: "assistant", content: "old reply 1" },
      { role: "user", content: "recent msg" },
      { role: "assistant", content: "recent reply" },
    ];
    const items = messagesToContextItems(messages, config);

    // Last 2 messages should be protected (priority 90)
    expect(items[3].priority).toBe(90);
    expect(items[4].priority).toBe(90);
    // Older messages should have lower priority
    expect(items[1].priority).toBeLessThan(90);
    expect(items[2].priority).toBeLessThan(90);
  });

  it("assigns increasing recency from 0 to 1", () => {
    const messages: GenericMessage[] = [
      { role: "user", content: "first" },
      { role: "assistant", content: "second" },
      { role: "user", content: "third" },
    ];
    const items = messagesToContextItems(messages, config);
    expect(items[0].recency).toBe(0);
    expect(items[1].recency).toBe(0.5);
    expect(items[2].recency).toBe(1);
  });

  it("estimates tokens for each message", () => {
    const messages: GenericMessage[] = [{ role: "user", content: "a b c d e" }];
    const items = messagesToContextItems(messages, config);
    expect(items[0].tokens).toBeGreaterThan(0);
  });
});

describe("contextItemsToMessages", () => {
  it("preserves original message objects in order", () => {
    const original: GenericMessage[] = [
      { role: "system", content: "sys" },
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi" },
    ];
    const keptItems = [
      {
        id: "msg-0",
        content: "sys",
        metadata: { originalIndex: 0, role: "system" },
      },
      {
        id: "msg-2",
        content: "hi",
        metadata: { originalIndex: 2, role: "assistant" },
      },
    ];

    const result = contextItemsToMessages(original, keptItems);
    expect(result).toHaveLength(2);
    expect(result[0]).toBe(original[0]); // Same reference
    expect(result[1]).toBe(original[2]);
  });

  it("injects a summary message when provided", () => {
    const original: GenericMessage[] = [
      { role: "system", content: "sys" },
      { role: "user", content: "recent" },
    ];
    const keptItems = [
      {
        id: "msg-0",
        content: "sys",
        metadata: { originalIndex: 0, role: "system" },
      },
      {
        id: "msg-1",
        content: "recent",
        metadata: { originalIndex: 1, role: "user" },
      },
    ];

    const result = contextItemsToMessages(
      original,
      keptItems,
      "Summary of dropped messages"
    );
    expect(result).toHaveLength(3);
    expect(result[0].role).toBe("system"); // original system
    expect(result[1].role).toBe("system"); // injected summary
    expect(result[1].content).toContain("Context summary");
    expect(result[2].role).toBe("user"); // original user
  });

  it("does not inject summary when not provided", () => {
    const original: GenericMessage[] = [{ role: "user", content: "hello" }];
    const keptItems = [
      {
        id: "msg-0",
        content: "hello",
        metadata: { originalIndex: 0, role: "user" },
      },
    ];

    const result = contextItemsToMessages(original, keptItems);
    expect(result).toHaveLength(1);
  });
});
