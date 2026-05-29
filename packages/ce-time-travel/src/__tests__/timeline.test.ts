import { describe, it, expect } from "vitest";
import { createTimeline } from "../timeline.js";
import type { ContextItem } from "@context-engineering/core";

function makeItem(
  id: string,
  content: string,
  overrides?: Partial<ContextItem>
): ContextItem {
  return { id, content, ...overrides };
}

describe("createTimeline", () => {
  it("starts on the default branch with no items", () => {
    const tl = createTimeline();
    expect(tl.currentBranch()).toBe("main");
    expect(tl.getItems()).toHaveLength(0);
  });

  it("respects custom default branch name", () => {
    const tl = createTimeline({ defaultBranch: "trunk" });
    expect(tl.currentBranch()).toBe("trunk");
  });

  describe("item operations", () => {
    it("setItems replaces items on the current branch", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "alpha"), makeItem("b", "beta")]);
      expect(tl.getItems()).toHaveLength(2);

      tl.setItems([makeItem("c", "gamma")]);
      expect(tl.getItems()).toHaveLength(1);
      expect(tl.getItems()[0].id).toBe("c");
    });

    it("addItems appends without duplicating existing IDs", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "alpha")]);
      tl.addItems(makeItem("b", "beta"), makeItem("a", "duplicate"));
      expect(tl.getItems()).toHaveLength(2);
    });

    it("removeItems removes by ID", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "alpha"), makeItem("b", "beta")]);
      tl.removeItems("a");
      const items = tl.getItems();
      expect(items).toHaveLength(1);
      expect(items[0].id).toBe("b");
    });

    it("getItems returns a deep copy", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "original")]);
      const items = tl.getItems();
      items[0].content = "mutated";
      expect(tl.getItems()[0].content).toBe("original");
    });
  });

  describe("checkpoint and rewind", () => {
    it("creates a named checkpoint and can rewind to it", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "v1")]);
      tl.checkpoint("version-1");

      tl.setItems([makeItem("a", "v2"), makeItem("b", "new")]);
      expect(tl.getItems()).toHaveLength(2);

      tl.rewind("version-1");
      const items = tl.getItems();
      expect(items).toHaveLength(1);
      expect(items[0].content).toBe("v1");
    });

    it("checkpoint stores metadata", () => {
      const tl = createTimeline();
      const snap = tl.checkpoint("tagged", { reason: "test" });
      expect(snap.metadata).toEqual({ reason: "test" });
    });

    it("rewind to nonexistent checkpoint throws", () => {
      const tl = createTimeline();
      expect(() => tl.rewind("nonexistent")).toThrow(
        'Snapshot "nonexistent" not found'
      );
    });

    it("rewind restores items as a deep copy", () => {
      const tl = createTimeline();
      const original = makeItem("a", "original", { metadata: { k: "v" } });
      tl.setItems([original]);
      tl.checkpoint("snap1");

      tl.setItems([]);
      tl.rewind("snap1");
      const items = tl.getItems();
      items[0].content = "mutated";
      items[0].metadata!["k"] = "changed";

      tl.rewind("snap1");
      expect(tl.getItems()[0].content).toBe("original");
      expect(tl.getItems()[0].metadata!["k"]).toBe("v");
    });
  });

  describe("branching", () => {
    it("fork creates an independent branch", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "shared")]);
      tl.checkpoint("base");

      tl.fork("feature");
      expect(tl.currentBranch()).toBe("feature");
      expect(tl.getItems()).toHaveLength(1);

      // Modify on feature branch
      tl.addItems(makeItem("b", "feature-only"));
      expect(tl.getItems()).toHaveLength(2);

      // Switch back to main -- should not have the feature item
      tl.checkout("main");
      expect(tl.getItems()).toHaveLength(1);
      expect(tl.getItems()[0].id).toBe("a");
    });

    it("changes on one branch do not affect another", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "main-item")]);
      tl.fork("branch-a");
      tl.setItems([makeItem("x", "branch-a-item")]);

      tl.checkout("main");
      expect(tl.getItems()[0].id).toBe("a");

      tl.checkout("branch-a");
      expect(tl.getItems()[0].id).toBe("x");
    });

    it("fork from a specific snapshot works", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "v1")]);
      const snap = tl.checkpoint("snap1");

      tl.setItems([makeItem("a", "v2"), makeItem("b", "new")]);
      tl.checkpoint("snap2");

      // Fork from snap1, not the current state
      tl.fork("from-snap1", snap.id);
      expect(tl.getItems()).toHaveLength(1);
      expect(tl.getItems()[0].content).toBe("v1");
    });

    it("fork with duplicate name throws", () => {
      const tl = createTimeline();
      tl.fork("feature");
      expect(() => tl.fork("feature")).toThrow("already exists");
    });

    it("checkout to nonexistent branch throws", () => {
      const tl = createTimeline();
      expect(() => tl.checkout("nope")).toThrow("does not exist");
    });

    it("listBranches returns all branches", () => {
      const tl = createTimeline();
      tl.fork("a");
      tl.checkout("main");
      tl.fork("b");

      const branches = tl.listBranches();
      const names = branches.map(b => b.name).sort();
      expect(names).toEqual(["a", "b", "main"]);
    });

    it("forked branch records parentBranch and forkPoint", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "base")]);
      tl.checkpoint("base-snap");

      const branch = tl.fork("child");
      expect(branch.parentBranch).toBe("main");
      expect(branch.forkPoint).toBeTruthy();
    });
  });

  describe("compare", () => {
    it("shows differences between branches", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "shared"), makeItem("b", "main-only")]);
      tl.fork("feature");
      tl.removeItems("b");
      tl.addItems(makeItem("c", "feature-only"));
      tl.setItems([
        makeItem("a", "modified on feature"),
        makeItem("c", "feature-only"),
      ]);

      const cmp = tl.compare("main", "feature");
      expect(cmp.branch1).toBe("main");
      expect(cmp.branch2).toBe("feature");
      expect(cmp.onlyInBranch1).toHaveLength(1);
      expect(cmp.onlyInBranch1[0].id).toBe("b");
      expect(cmp.onlyInBranch2).toHaveLength(1);
      expect(cmp.onlyInBranch2[0].id).toBe("c");
      expect(cmp.modified).toHaveLength(1);
      expect(cmp.modified[0].id).toBe("a");
      expect(cmp.quality1).toBeDefined();
      expect(cmp.quality2).toBeDefined();
    });

    it("shows no differences for identical branches", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "same")]);
      tl.fork("copy");

      const cmp = tl.compare("main", "copy");
      expect(cmp.onlyInBranch1).toHaveLength(0);
      expect(cmp.onlyInBranch2).toHaveLength(0);
      expect(cmp.modified).toHaveLength(0);
      expect(cmp.common).toHaveLength(1);
    });
  });

  describe("merge", () => {
    it("merges another branch into the current branch", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "main-item")]);

      tl.fork("feature");
      tl.addItems(makeItem("b", "feature-item"));

      tl.checkout("main");
      const result = tl.merge("feature", { strategy: "union" });

      expect(result.items).toHaveLength(2);
      expect(result.fromBranch).toBe("feature");
      expect(result.intoBranch).toBe("main");
      expect(tl.getItems()).toHaveLength(2);
    });

    it("merge with conflicts reports conflict count", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "main-version", { recency: 1 })]);

      tl.fork("feature");
      tl.setItems([makeItem("a", "feature-version", { recency: 9 })]);

      tl.checkout("main");
      const result = tl.merge("feature", { strategy: "union" });

      expect(result.conflicts).toBe(1);
      // Feature has higher recency, so it should win
      expect(tl.getItems()[0].content).toBe("feature-version");
    });

    it("creates a merge snapshot in history", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "base")]);
      tl.fork("feature");
      tl.addItems(makeItem("b", "extra"));

      tl.checkout("main");
      tl.merge("feature");

      const hist = tl.history();
      const mergeSnap = hist.find(s => s.name.startsWith("merge:"));
      expect(mergeSnap).toBeDefined();
      expect(mergeSnap!.name).toBe("merge:feature");
    });
  });

  describe("history", () => {
    it("returns snapshots in chronological order", () => {
      const tl = createTimeline();
      tl.checkpoint("first");
      tl.checkpoint("second");
      tl.checkpoint("third");

      const hist = tl.history();
      expect(hist.length).toBeGreaterThanOrEqual(3);
      for (let i = 1; i < hist.length; i++) {
        expect(hist[i].createdAt).toBeGreaterThanOrEqual(hist[i - 1].createdAt);
      }
    });

    it("only returns snapshots for the current branch", () => {
      const tl = createTimeline();
      tl.checkpoint("main-snap");
      tl.fork("feature");
      tl.checkpoint("feature-snap");

      const featureHist = tl.history();
      expect(featureHist.every(s => s.branchName === "feature")).toBe(true);

      tl.checkout("main");
      const mainHist = tl.history();
      expect(mainHist.every(s => s.branchName === "main")).toBe(true);
    });

    it("returns deep copies that cannot corrupt stored history", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "original")]);
      tl.checkpoint("cp1");

      // Mutate items of a snapshot returned by history()
      const hist = tl.history();
      const target = hist.find(snap => snap.name === "cp1");
      target!.items[0].content = "edited";
      target!.items.push(makeItem("b", "injected"));

      // A fresh history() read must be unaffected
      const fresh = tl.history().find(snap => snap.name === "cp1");
      expect(fresh!.items).toHaveLength(1);
      expect(fresh!.items[0].content).toBe("original");

      // And a rewind must restore the original, uncorrupted state
      tl.setItems([]);
      tl.rewind("cp1");
      const restored = tl.getItems();
      expect(restored).toHaveLength(1);
      expect(restored[0].content).toBe("original");
    });
  });

  describe("getSnapshot", () => {
    it("finds a snapshot by name", () => {
      const tl = createTimeline();
      tl.checkpoint("findme");
      const snap = tl.getSnapshot("findme");
      expect(snap).not.toBeNull();
      expect(snap!.name).toBe("findme");
    });

    it("finds a snapshot by ID", () => {
      const tl = createTimeline();
      const created = tl.checkpoint("byid");
      const snap = tl.getSnapshot(created.id);
      expect(snap).not.toBeNull();
      expect(snap!.id).toBe(created.id);
    });

    it("returns null for nonexistent snapshot", () => {
      const tl = createTimeline();
      expect(tl.getSnapshot("nonexistent")).toBeNull();
    });

    it("returns a deep copy that cannot corrupt stored history", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "original", { metadata: { k: "v" } })]);
      tl.checkpoint("cp1");

      // Mutate the returned snapshot's items in place
      const snap = tl.getSnapshot("cp1");
      snap!.items[0].content = "edited";
      snap!.items[0].metadata!["k"] = "changed";
      snap!.items.push(makeItem("b", "injected"));

      // A fresh read must be unaffected
      const fresh = tl.getSnapshot("cp1");
      expect(fresh!.items).toHaveLength(1);
      expect(fresh!.items[0].content).toBe("original");
      expect(fresh!.items[0].metadata!["k"]).toBe("v");

      // And a rewind must restore the original, uncorrupted state
      tl.setItems([]);
      tl.rewind("cp1");
      const restored = tl.getItems();
      expect(restored).toHaveLength(1);
      expect(restored[0].content).toBe("original");
      expect(restored[0].metadata!["k"]).toBe("v");
    });

    it("returns a fresh reference on each call", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "x")]);
      tl.checkpoint("cp1");

      const first = tl.getSnapshot("cp1");
      const second = tl.getSnapshot("cp1");
      expect(first).not.toBe(second);
      expect(first!.items).not.toBe(second!.items);
    });
  });

  describe("exportState / importState", () => {
    it("round-trip preserves state", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "alpha"), makeItem("b", "beta")]);
      tl.checkpoint("v1");
      tl.fork("feature");
      tl.addItems(makeItem("c", "gamma"));
      tl.checkpoint("feature-v1");

      const state = tl.exportState();

      const tl2 = createTimeline();
      tl2.importState(state);

      expect(tl2.currentBranch()).toBe("feature");
      expect(tl2.getItems()).toHaveLength(3);
      expect(tl2.listBranches()).toHaveLength(2);

      tl2.checkout("main");
      expect(tl2.getItems()).toHaveLength(2);
    });

    it("exported state is a deep copy", () => {
      const tl = createTimeline();
      tl.setItems([makeItem("a", "original")]);
      tl.checkpoint("v1");

      const state = tl.exportState();

      // Mutate original timeline
      tl.setItems([makeItem("a", "mutated")]);

      // Import into new timeline -- should have original value
      const tl2 = createTimeline();
      tl2.importState(state);
      tl2.rewind("v1");
      expect(tl2.getItems()[0].content).toBe("original");
    });
  });

  describe("autoSnapshot option", () => {
    it("creates snapshots automatically on setItems", () => {
      const tl = createTimeline({ autoSnapshot: true });
      const histBefore = tl.history().length;

      tl.setItems([makeItem("a", "alpha")]);
      const histAfter = tl.history().length;

      expect(histAfter).toBeGreaterThan(histBefore);
    });

    it("creates snapshots automatically on addItems", () => {
      const tl = createTimeline({ autoSnapshot: true });
      tl.setItems([makeItem("a", "alpha")]);
      const histBefore = tl.history().length;

      tl.addItems(makeItem("b", "beta"));
      const histAfter = tl.history().length;

      expect(histAfter).toBeGreaterThan(histBefore);
    });

    it("creates snapshots automatically on removeItems", () => {
      const tl = createTimeline({ autoSnapshot: true });
      tl.setItems([makeItem("a", "alpha")]);
      const histBefore = tl.history().length;

      tl.removeItems("a");
      const histAfter = tl.history().length;

      expect(histAfter).toBeGreaterThan(histBefore);
    });
  });

  describe("maxSnapshots pruning", () => {
    it("prunes oldest snapshots when limit is exceeded", () => {
      const tl = createTimeline({ maxSnapshots: 5 });

      for (let i = 0; i < 10; i++) {
        tl.setItems([makeItem("a", `version-${i}`)]);
        tl.checkpoint(`v${i}`);
      }

      const hist = tl.history();
      expect(hist.length).toBeLessThanOrEqual(5);
    });

    it("never prunes branch head or fork point snapshots", () => {
      const tl = createTimeline({ maxSnapshots: 3 });
      tl.setItems([makeItem("a", "base")]);
      tl.checkpoint("base");
      tl.fork("feature");

      // Add more snapshots to trigger pruning
      tl.checkout("main");
      for (let i = 0; i < 5; i++) {
        tl.checkpoint(`extra-${i}`);
      }

      // Both branches should still be valid
      const branches = tl.listBranches();
      for (const branch of branches) {
        const headSnap = tl.getSnapshot(branch.headSnapshotId);
        expect(headSnap).not.toBeNull();
      }
    });
  });
});
