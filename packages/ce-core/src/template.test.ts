import { describe, it, expect } from "vitest";
import { createContextItem } from "./types.js";
import {
  toMessages,
  formatForAnthropic,
  formatForOpenAI,
  compileToMessages,
  DEFAULT_SECTION_RULES,
} from "./template.js";
import type { PromptTemplateConfig, SectionRule } from "./template.js";
import type { Turn } from "./compaction.js";

describe("toMessages", () => {
  it("maps items to messages using default rules (system kind -> system role)", () => {
    const items = [
      createContextItem("s1", "system prompt", { kind: "system" }),
    ];
    const { messages } = toMessages(items);
    expect(messages).toHaveLength(1);
    expect(messages[0].role).toBe("system");
    expect(messages[0].content).toContain("system prompt");
  });

  it("items with kind 'query' go to user role", () => {
    const items = [createContextItem("q1", "what is AI?", { kind: "query" })];
    const { messages } = toMessages(items);
    expect(messages[0].role).toBe("user");
  });

  it("items with kind 'retrieval' get '[Retrieved]\\n' prefix", () => {
    const items = [
      createContextItem("r1", "retrieved doc", { kind: "retrieval" }),
    ];
    const { messages } = toMessages(items);
    expect(messages[0].content).toContain("[Retrieved]");
    expect(messages[0].content).toContain("retrieved doc");
  });

  it("unknown kinds use fallbackRole (default 'system')", () => {
    const items = [
      createContextItem("x1", "mystery content", { kind: "custom_kind" }),
    ];
    const { messages } = toMessages(items);
    expect(messages[0].role).toBe("system");
  });

  it("custom fallbackRole applies to unknown kinds", () => {
    const items = [
      createContextItem("x1", "mystery content", { kind: "custom_kind" }),
    ];
    const config: PromptTemplateConfig = { fallbackRole: "user" };
    const { messages } = toMessages(items, config);
    expect(messages[0].role).toBe("user");
  });

  it("merge: true combines items of same kind into one message", () => {
    const items = [
      createContextItem("s1", "first system", { kind: "system" }),
      createContextItem("s2", "second system", { kind: "system" }),
    ];
    // system kind has merge: true by default
    const { messages } = toMessages(items);
    const systemMessages = messages.filter(m => m.role === "system");
    expect(systemMessages).toHaveLength(1);
    expect(systemMessages[0].content).toContain("first system");
    expect(systemMessages[0].content).toContain("second system");
  });

  it("mergeSeparator is used between merged items", () => {
    const items = [
      createContextItem("s1", "first", { kind: "system" }),
      createContextItem("s2", "second", { kind: "system" }),
    ];
    const sections: SectionRule[] = [
      {
        kind: "system",
        role: "system",
        order: 0,
        merge: true,
        mergeSeparator: "---",
      },
    ];
    const { messages } = toMessages(items, { sections });
    const systemMsg = messages.find(m => m.role === "system");
    expect(systemMsg!.content).toContain("---");
  });

  it("metadata.role overrides section rule role", () => {
    const items = [
      createContextItem("s1", "override me", {
        kind: "system",
        metadata: { role: "user" },
      }),
    ];
    const { messages } = toMessages(items);
    expect(messages[0].role).toBe("user");
  });

  it("empty input returns empty messages", () => {
    const { messages } = toMessages([]);
    expect(messages).toHaveLength(0);
  });

  it("cache breakpoint from metadata._cacheBreakpoint", () => {
    const items = [
      createContextItem("s1", "cached content", {
        kind: "system",
        metadata: { _cacheBreakpoint: true },
      }),
    ];
    const { messages } = toMessages(items);
    expect(messages[0].cacheControl).toEqual({ type: "ephemeral" });
  });

  it("cache breakpoint from section rule cacheBreakpoint", () => {
    const items = [createContextItem("s1", "content", { kind: "system" })];
    const sections: SectionRule[] = [
      {
        kind: "system",
        role: "system",
        order: 0,
        merge: true,
        cacheBreakpoint: true,
      },
    ];
    const { messages } = toMessages(items, { sections });
    expect(messages[0].cacheControl).toEqual({ type: "ephemeral" });
  });

  it("stats include sectionCounts, systemTokens, userTokens, assistantTokens", () => {
    const items = [
      createContextItem("s1", "system text", { kind: "system" }),
      createContextItem("q1", "user text", { kind: "query" }),
    ];
    const { stats } = toMessages(items);
    expect(stats).toHaveProperty("sectionCounts");
    expect(stats).toHaveProperty("systemTokens");
    expect(stats).toHaveProperty("userTokens");
    expect(stats).toHaveProperty("assistantTokens");
  });

  it("includedItemIds lists all item ids", () => {
    const items = [
      createContextItem("alpha", "one", { kind: "system" }),
      createContextItem("beta", "two", { kind: "query" }),
    ];
    const { includedItemIds } = toMessages(items);
    expect(includedItemIds).toContain("alpha");
    expect(includedItemIds).toContain("beta");
    expect(includedItemIds).toHaveLength(2);
  });

  it("orders items by section rule order", () => {
    // query (order 100) should come after system (order 0)
    const items = [
      createContextItem("q1", "question", { kind: "query" }),
      createContextItem("s1", "system prompt", { kind: "system" }),
    ];
    const { messages } = toMessages(items);
    expect(messages[0].role).toBe("system");
    expect(messages[1].role).toBe("user");
  });
});

describe("formatForAnthropic", () => {
  it("extracts system messages into system string", () => {
    const items = [
      createContextItem("s1", "system instructions", { kind: "system" }),
      createContextItem("q1", "user question", { kind: "query" }),
    ];
    const prompt = toMessages(items);
    const result = formatForAnthropic(prompt);
    expect(result.system).toContain("system instructions");
    expect(result.messages.every(m => m.role !== "system")).toBe(true);
  });

  it("with cacheBreakpoints: true, uses content block format", () => {
    const items = [
      createContextItem("s1", "cached system", {
        kind: "system",
        metadata: { _cacheBreakpoint: true },
      }),
    ];
    const prompt = toMessages(items);
    const result = formatForAnthropic(prompt, { cacheBreakpoints: true });
    expect(Array.isArray(result.system)).toBe(true);
    const blocks = result.system as Array<{
      type: string;
      text: string;
      cache_control?: unknown;
    }>;
    expect(blocks[0].type).toBe("text");
    expect(blocks[0].cache_control).toEqual({ type: "ephemeral" });
  });

  it("non-system messages are user/assistant only", () => {
    const items = [
      createContextItem("s1", "sys", { kind: "system" }),
      createContextItem("q1", "question", { kind: "query" }),
    ];
    const prompt = toMessages(items);
    const result = formatForAnthropic(prompt);
    for (const msg of result.messages) {
      expect(["user", "assistant"]).toContain(msg.role);
    }
  });

  it("empty system returns empty string", () => {
    const items = [createContextItem("q1", "question", { kind: "query" })];
    const prompt = toMessages(items);
    const result = formatForAnthropic(prompt);
    expect(result.system).toBe("");
  });
});

describe("formatForOpenAI", () => {
  it("system messages come first", () => {
    const items = [
      createContextItem("q1", "question", { kind: "query" }),
      createContextItem("s1", "system msg", { kind: "system" }),
    ];
    const prompt = toMessages(items);
    const result = formatForOpenAI(prompt);
    const firstSystemIdx = result.messages.findIndex(m => m.role === "system");
    const firstNonSystemIdx = result.messages.findIndex(
      m => m.role !== "system"
    );
    if (firstSystemIdx >= 0 && firstNonSystemIdx >= 0) {
      expect(firstSystemIdx).toBeLessThan(firstNonSystemIdx);
    }
  });

  it("preserves message order for non-system", () => {
    const items = [
      createContextItem("q1", "first question", { kind: "query" }),
      createContextItem("q2", "second question", { kind: "query" }),
    ];
    const prompt = toMessages(items);
    const result = formatForOpenAI(prompt);
    const userMessages = result.messages.filter(m => m.role === "user");
    expect(userMessages[0].content).toContain("first question");
    expect(userMessages[1].content).toContain("second question");
  });
});

describe("compileToMessages", () => {
  it("converts Turn[] to messages (user/assistant roles preserved)", () => {
    const turns: Turn[] = [
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi there" },
    ];
    const { messages } = compileToMessages({
      turns,
      items: [],
      totalTokens: 0,
    });
    expect(messages[0].role).toBe("user");
    expect(messages[0].content).toContain("hello");
    expect(messages[1].role).toBe("assistant");
    expect(messages[1].content).toContain("hi there");
  });

  it("tool turns become user role", () => {
    const turns: Turn[] = [{ role: "tool", content: "tool output" }];
    const { messages } = compileToMessages({
      turns,
      items: [],
      totalTokens: 0,
    });
    expect(messages[0].role).toBe("user");
  });

  it("summary turns are included", () => {
    const turns: Turn[] = [
      { role: "system", content: "conversation summary", isSummary: true },
    ];
    const { messages } = compileToMessages({
      turns,
      items: [],
      totalTokens: 0,
    });
    expect(messages.some(m => m.content.includes("conversation summary"))).toBe(
      true
    );
  });

  it("items are appended after turns using section rules", () => {
    const turns: Turn[] = [{ role: "user", content: "hello" }];
    const items = [
      createContextItem("s1", "system context", { kind: "system" }),
    ];
    const { messages } = compileToMessages({ turns, items, totalTokens: 0 });
    expect(messages.length).toBeGreaterThan(1);
    const hasSystem = messages.some(
      m => m.role === "system" && m.content.includes("system context")
    );
    expect(hasSystem).toBe(true);
  });
});

describe("DEFAULT_SECTION_RULES", () => {
  it("has expected default rules", () => {
    expect(DEFAULT_SECTION_RULES.length).toBeGreaterThan(0);
    const systemRule = DEFAULT_SECTION_RULES.find(r => r.kind === "system");
    expect(systemRule).toBeDefined();
    expect(systemRule!.role).toBe("system");
    expect(systemRule!.merge).toBe(true);
  });
});
