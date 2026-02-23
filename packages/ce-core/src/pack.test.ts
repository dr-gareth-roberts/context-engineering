import { describe, expect, it } from "vitest";
import { pack } from "./pack";
import type { ContextItem } from "./types";

const items: ContextItem[] = [
  { id: "a", content: "High priority", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 }
];

describe("pack", () => {
  it("selects highest scored items within budget", () => {
    const packResult = pack(items, { maxTokens: 90 });
    const selectedIds = packResult.selected.map((item) => item.id);
    expect(selectedIds).toContain("a");
    expect(selectedIds).toContain("c");
    expect(selectedIds).not.toContain("b");
  });

  it("uses compression when allowed", () => {
    const compressedItems: ContextItem[] = [
      {
        id: "a",
        content: "Long content",
        priority: 10,
        tokens: 100,
        compressions: [{ content: "Short", tokens: 30, note: "summary" }]
      }
    ];

    const packResult = pack(compressedItems, { maxTokens: 40 }, { allowCompression: true });
    expect(packResult.selected[0].content).toBe("Short");
  });
});
