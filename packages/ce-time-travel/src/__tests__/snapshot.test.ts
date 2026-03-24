import { describe, it, expect } from "vitest";
import { createSnapshot, diffSnapshots, deepCopyItems } from "../snapshot.js";
import type { ContextItem } from "@context-engineering/core";

function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return { id, content, ...overrides };
}

describe("createSnapshot", () => {
  it("creates a snapshot with auto-generated ID and timestamp", () => {
    const items = [makeItem("a", "hello")];
    const snap = createSnapshot("v1", items, "main", null);

    expect(snap.id).toMatch(/^snap_/);
    expect(snap.name).toBe("v1");
    expect(snap.branchName).toBe("main");
    expect(snap.parentId).toBeNull();
    expect(snap.createdAt).toBeGreaterThan(0);
    expect(snap.items).toHaveLength(1);
    expect(snap.items[0].content).toBe("hello");
  });

  it("stores a deep copy so mutations do not affect the snapshot", () => {
    const items = [makeItem("a", "original", { metadata: { key: "val" } })];
    const snap = createSnapshot("v1", items, "main", null);

    items[0].content = "mutated";
    items[0].metadata!["key"] = "changed";

    expect(snap.items[0].content).toBe("original");
    expect(snap.items[0].metadata!["key"]).toBe("val");
  });

  it("stores metadata when provided", () => {
    const snap = createSnapshot("v1", [], "main", null, { author: "test" });
    expect(snap.metadata).toEqual({ author: "test" });
  });

  it("links to parent snapshot ID", () => {
    const snap = createSnapshot("v2", [], "main", "snap_parent_1");
    expect(snap.parentId).toBe("snap_parent_1");
  });

  it("generates unique IDs for successive snapshots", () => {
    const s1 = createSnapshot("a", [], "main", null);
    const s2 = createSnapshot("b", [], "main", null);
    expect(s1.id).not.toBe(s2.id);
  });
});

describe("deepCopyItems", () => {
  it("produces an independent copy of items", () => {
    const original = [
      makeItem("a", "hello", {
        metadata: { k: "v" },
        links: ["http://x"],
        embedding: [1, 2, 3],
        dependsOn: ["dep1"],
      }),
    ];
    const copy = deepCopyItems(original);

    original[0].content = "changed";
    original[0].metadata!["k"] = "changed";
    original[0].links!.push("http://y");
    original[0].embedding!.push(4);
    original[0].dependsOn!.push("dep2");

    expect(copy[0].content).toBe("hello");
    expect(copy[0].metadata!["k"]).toBe("v");
    expect(copy[0].links).toEqual(["http://x"]);
    expect(copy[0].embedding).toEqual([1, 2, 3]);
    expect(copy[0].dependsOn).toEqual(["dep1"]);
  });
});

describe("diffSnapshots", () => {
  it("detects added items", () => {
    const a = createSnapshot("a", [makeItem("1", "one")], "main", null);
    const b = createSnapshot(
      "b",
      [makeItem("1", "one"), makeItem("2", "two")],
      "main",
      null
    );

    const diff = diffSnapshots(a, b);
    expect(diff.added).toHaveLength(1);
    expect(diff.added[0].id).toBe("2");
    expect(diff.removed).toHaveLength(0);
    expect(diff.modified).toHaveLength(0);
    expect(diff.unchanged).toHaveLength(1);
  });

  it("detects removed items", () => {
    const a = createSnapshot(
      "a",
      [makeItem("1", "one"), makeItem("2", "two")],
      "main",
      null
    );
    const b = createSnapshot("b", [makeItem("1", "one")], "main", null);

    const diff = diffSnapshots(a, b);
    expect(diff.removed).toHaveLength(1);
    expect(diff.removed[0].id).toBe("2");
    expect(diff.added).toHaveLength(0);
  });

  it("detects modified items by content difference", () => {
    const a = createSnapshot("a", [makeItem("1", "old content")], "main", null);
    const b = createSnapshot("b", [makeItem("1", "new content")], "main", null);

    const diff = diffSnapshots(a, b);
    expect(diff.modified).toHaveLength(1);
    expect(diff.modified[0].id).toBe("1");
    expect(diff.modified[0].before.content).toBe("old content");
    expect(diff.modified[0].after.content).toBe("new content");
    expect(diff.unchanged).toHaveLength(0);
  });

  it("identifies unchanged items correctly", () => {
    const items = [makeItem("1", "same"), makeItem("2", "also same")];
    const a = createSnapshot("a", items, "main", null);
    const b = createSnapshot("b", items, "main", null);

    const diff = diffSnapshots(a, b);
    expect(diff.unchanged).toHaveLength(2);
    expect(diff.added).toHaveLength(0);
    expect(diff.removed).toHaveLength(0);
    expect(diff.modified).toHaveLength(0);
  });

  it("handles empty snapshots", () => {
    const a = createSnapshot("a", [], "main", null);
    const b = createSnapshot("b", [], "main", null);

    const diff = diffSnapshots(a, b);
    expect(diff.added).toHaveLength(0);
    expect(diff.removed).toHaveLength(0);
    expect(diff.modified).toHaveLength(0);
    expect(diff.unchanged).toHaveLength(0);
  });
});
