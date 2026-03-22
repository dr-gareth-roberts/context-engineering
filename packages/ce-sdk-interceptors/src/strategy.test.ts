import { describe, it, expect, vi } from "vitest";
import { applyStrategy } from "./strategy.js";
import type { ContextPack } from "@context-engineering/core";
import type { GenericMessage } from "./message-converter.js";

function makePack(selectedIndices: number[]): ContextPack {
  return {
    budget: { maxTokens: 1000 },
    selected: selectedIndices.map(i => ({
      id: `msg-${i}`,
      content: `message ${i}`,
      metadata: { originalIndex: i },
    })),
    dropped: [],
    totalTokens: 100,
  };
}

const messages: GenericMessage[] = [
  { role: "system", content: "You are helpful" },
  { role: "user", content: "First question about programming" },
  { role: "assistant", content: "Here is my answer about programming" },
  { role: "user", content: "Follow up question" },
  { role: "assistant", content: "Follow up answer" },
];

describe("applyStrategy", () => {
  it("returns undefined for trim strategy", async () => {
    const pack = makePack([0, 3, 4]);
    const result = await applyStrategy("trim", messages, pack);
    expect(result).toBeUndefined();
  });

  it("returns a bullet-point summary for summarize strategy", async () => {
    const pack = makePack([0, 3, 4]); // messages 1, 2 dropped
    const result = await applyStrategy("summarize", messages, pack);
    expect(result).toBeDefined();
    expect(result).toContain("Earlier conversation");
    expect(result).toContain("[user]");
    expect(result).toContain("[assistant]");
  });

  it("returns undefined when no messages were dropped", async () => {
    const pack = makePack([0, 1, 2, 3, 4]); // all kept
    const result = await applyStrategy("summarize", messages, pack);
    expect(result).toBeUndefined();
  });

  it("calls custom function with dropped messages", async () => {
    const customFn = vi.fn().mockResolvedValue("custom summary");
    const pack = makePack([0, 4]); // messages 1, 2, 3 dropped

    const result = await applyStrategy(customFn, messages, pack);
    expect(result).toBe("custom summary");
    expect(customFn).toHaveBeenCalledOnce();

    const dropped = customFn.mock.calls[0][0];
    expect(dropped).toHaveLength(3);
    expect(dropped[0].role).toBe("user");
    expect(dropped[0].index).toBe(1);
  });
});
