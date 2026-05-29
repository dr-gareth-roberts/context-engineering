import { describe, it, expect, vi } from "vitest";
import { createEntanglementMesh } from "../mesh.js";
import type { EntanglementMesh } from "../types.js";

function item(id: string, content?: string, kind?: string) {
  return {
    id,
    content: content ?? `content for ${id}`,
    kind,
    priority: 5,
    tokens: 10,
  };
}

describe("AgentHandle", () => {
  let mesh: EntanglementMesh;

  beforeEach(() => {
    mesh = createEntanglementMesh();
  });

  describe("entangle", () => {
    it("publishes an item to the mesh so other agents see it", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("shared-1"));

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending).toHaveLength(1);
      expect(pending[0].item.id).toBe("shared-1");
    });

    it("applies priority override from options", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("p-item"), { priority: 99 });

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending[0].item.priority).toBe(99);
    });

    it("sets propagation to next-pack by default", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("np-item"));

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending[0].propagation).toBe("next-pack");
    });

    it("respects expiresIn option", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("ttl-item"), { expiresIn: 5000 });

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending[0].expiresAt).toBeDefined();
      // expiresAt should be roughly now + 5000
      expect(pending[0].expiresAt!).toBeGreaterThan(Date.now() - 1000);
    });

    it("attaches metadata from options", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("meta-item"), {
        metadata: { reason: "important" },
      });

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending[0].metadata).toEqual({ reason: "important" });
    });
  });

  describe("pack", () => {
    it("includes entangled items from other agents in the pack", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("from-a"));

      const result = handleB.pack([item("own-1")]);
      const selectedIds = result.selected.map(s => s.id);
      expect(selectedIds).toContain("from-a");
      expect(selectedIds).toContain("own-1");
    });

    it("returns entangledItems and ownItems metadata", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("from-a"));

      const result = handleB.pack([item("own-1")]);
      expect(result.ownItems.map(i => i.id)).toContain("own-1");
      expect(result.entangledItems.map(ei => ei.item.id)).toContain("from-a");
    });

    it("does not include on-demand items in pack", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("on-demand-item"), {
        propagation: "on-demand",
      });

      const result = handleB.pack([item("own-1")]);
      const selectedIds = result.selected.map(s => s.id);
      expect(selectedIds).not.toContain("on-demand-item");
    });

    it("uses agent's registered budget when no budget argument given", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      // Agent B has a tiny budget
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 50 },
      });

      // Entangle many items
      for (let i = 0; i < 10; i++) {
        handleA.entangle(item(`item-${i}`, "x".repeat(100)));
      }

      const result = handleB.pack([]);
      // Budget should constrain selection
      expect(result.totalTokens).toBeLessThanOrEqual(50);
    });

    it("respects budget — entangled items can be dropped", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 10000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 30 },
      });

      handleA.entangle({
        id: "big",
        content: "x".repeat(500),
        priority: 1,
        tokens: 500,
      });

      const result = handleB.pack(
        [{ id: "own", content: "small", priority: 10, tokens: 5 }],
        { maxTokens: 30 }
      );

      // Own item should be selected, entangled item may be dropped
      expect(result.selected.map(s => s.id)).toContain("own");
    });
  });

  describe("getPending", () => {
    it("returns all pending items for the agent", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("i1"));
      handleA.entangle(item("i2"));

      expect(handleB.getPending()).toHaveLength(2);
    });

    it("includes on-demand items in getPending", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("od-item"), { propagation: "on-demand" });

      const pending = handleB.getPending();
      expect(pending).toHaveLength(1);
      expect(pending[0].item.id).toBe("od-item");
    });
  });

  describe("acknowledge", () => {
    it("removes acknowledged immediate items from pending", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("ack-item"), { propagation: "immediate" });

      expect(handleB.getPending()).toHaveLength(1);

      handleB.acknowledge("ack-item");

      expect(handleB.getPending()).toHaveLength(0);
    });

    it("does not affect next-pack items", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("np-item"), { propagation: "next-pack" });

      handleB.acknowledge("np-item");

      // next-pack items are not filtered by acknowledgment
      expect(handleB.getPending()).toHaveLength(1);
    });

    it("garbage-collects acknowledged IDs once their items are pruned from the store", () => {
      // Small mesh: store keeps at most 2 items, so older entangled items are
      // pruned away (agent-handle.ts entangle() splice). A persistent agent that
      // acknowledges each immediate item would otherwise retain a stale ID forever.
      const leakyMesh = createEntanglementMesh({ maxItems: 2 });
      const producer = leakyMesh.register("producer", {
        budget: { maxTokens: 1000 },
      });
      const consumer = leakyMesh.register("consumer", {
        budget: { maxTokens: 1000 },
      });

      // Observe internal Set GC: without the fix, acknowledge() only ever calls
      // Set.prototype.add and never .delete; the fix deletes stale IDs.
      const deletedIds: unknown[] = [];
      const originalDelete = Set.prototype.delete;
      const deleteSpy = vi
        .spyOn(Set.prototype, "delete")
        .mockImplementation(function (this: Set<unknown>, value: unknown) {
          deletedIds.push(value);
          return originalDelete.call(this, value);
        });

      try {
        // Entangle and acknowledge many immediate items. maxItems=2 keeps only
        // the two most recent in store.items, so earlier IDs become stale.
        for (let i = 0; i < 10; i++) {
          producer.entangle(item(`leak-${i}`), { propagation: "immediate" });
          consumer.acknowledge(`leak-${i}`);
        }
      } finally {
        deleteSpy.mockRestore();
      }

      // The fix must have pruned at least one stale acknowledged ID. The most
      // recently acknowledged IDs (still in store) must NOT be deleted.
      expect(deletedIds).toContain("leak-0");
      expect(deletedIds).not.toContain("leak-9");
    });

    it("keeps live acknowledged immediate items filtered when the GC sweep fires", () => {
      // Behaviour preservation: when the GC branch actually runs, it must drop
      // only stale (pruned) IDs and must NOT resurface a still-live, still-acked
      // immediate item back into pending (the regression the prescription warns
      // against). maxItems=2 forces the sweep to fire on the third acknowledge.
      const leakyMesh = createEntanglementMesh({ maxItems: 2 });
      const producer = leakyMesh.register("producer", {
        budget: { maxTokens: 1000 },
      });
      const consumer = leakyMesh.register("consumer", {
        budget: { maxTokens: 1000 },
      });

      producer.entangle(item("stale"), { propagation: "immediate" });
      consumer.acknowledge("stale"); // acked={stale}, store=[stale]
      producer.entangle(item("mid"), { propagation: "immediate" });
      consumer.acknowledge("mid"); // acked={stale,mid}, store=[stale,mid] (2>2 false)
      producer.entangle(item("keep-me"), { propagation: "immediate" });
      // store=[mid,keep-me] (stale pruned); acked.size 3 > store 2 -> GC fires.
      consumer.acknowledge("keep-me");

      // keep-me is live AND acknowledged -> must stay filtered (not resurfaced).
      const pendingIds = consumer.getPending().map(ei => ei.item.id);
      expect(pendingIds).not.toContain("keep-me");
      expect(pendingIds).not.toContain("mid");
    });
  });

  describe("scope filtering", () => {
    it("agent cannot see its own entangled items", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("self-item"));

      expect(handleA.getPending()).toHaveLength(0);
    });

    it("scoped items only reach targeted agents", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });
      const handleC = mesh.register("agent-c", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("scoped"), { scope: ["agent-b"] });

      expect(handleB.getPending()).toHaveLength(1);
      expect(handleC.getPending()).toHaveLength(0);
    });
  });

  describe("kind filtering", () => {
    it("agent with kind filter only receives matching items", () => {
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
        kindFilter: ["code"],
      });

      handleA.entangle(item("code-item", "code content", "code"));
      handleA.entangle(item("doc-item", "doc content", "doc"));

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending).toHaveLength(1);
      expect(pending[0].item.id).toBe("code-item");
    });
  });

  describe("unregister", () => {
    it("removes agent from the mesh", () => {
      const handle = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });

      expect(mesh.getAgent("agent-a")).not.toBeNull();

      handle.unregister();

      expect(mesh.getAgent("agent-a")).toBeNull();
      expect(mesh.listAgents()).toHaveLength(0);
    });
  });
});
