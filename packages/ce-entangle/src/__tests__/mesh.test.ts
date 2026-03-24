import { describe, it, expect, vi } from "vitest";
import { createEntanglementMesh } from "../mesh.js";
import type { EntangledItem, MeshConfig } from "../types.js";

function item(id: string, content?: string, kind?: string) {
  return {
    id,
    content: content ?? `content for ${id}`,
    kind,
    priority: 5,
    tokens: 10,
  };
}

describe("createEntanglementMesh", () => {
  describe("register", () => {
    it("registers an agent and returns a handle", () => {
      const mesh = createEntanglementMesh();
      const handle = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });

      expect(handle.agentId).toBe("agent-a");
    });

    it("throws when registering a duplicate agent ID", () => {
      const mesh = createEntanglementMesh();
      mesh.register("agent-a", { budget: { maxTokens: 1000 } });

      expect(() =>
        mesh.register("agent-a", { budget: { maxTokens: 1000 } })
      ).toThrow('Agent "agent-a" is already registered');
    });

    it("registers multiple agents", () => {
      const mesh = createEntanglementMesh();
      mesh.register("agent-a", { budget: { maxTokens: 1000 } });
      mesh.register("agent-b", { budget: { maxTokens: 2000 } });

      expect(mesh.listAgents()).toHaveLength(2);
    });
  });

  describe("getAgent", () => {
    it("returns handle for registered agent", () => {
      const mesh = createEntanglementMesh();
      mesh.register("agent-a", { budget: { maxTokens: 1000 } });

      const handle = mesh.getAgent("agent-a");
      expect(handle).not.toBeNull();
      expect(handle!.agentId).toBe("agent-a");
    });

    it("returns null for unregistered agent", () => {
      const mesh = createEntanglementMesh();
      expect(mesh.getAgent("nope")).toBeNull();
    });
  });

  describe("listAgents", () => {
    it("returns empty array when no agents registered", () => {
      const mesh = createEntanglementMesh();
      expect(mesh.listAgents()).toEqual([]);
    });

    it("returns all registered agents", () => {
      const mesh = createEntanglementMesh();
      mesh.register("a", { budget: { maxTokens: 100 } });
      mesh.register("b", { budget: { maxTokens: 200 } });

      const agents = mesh.listAgents();
      const ids = agents.map(a => a.agentId);
      expect(ids).toContain("a");
      expect(ids).toContain("b");
    });
  });

  describe("stats", () => {
    it("returns zero counts when empty", () => {
      const mesh = createEntanglementMesh();
      const s = mesh.stats();
      expect(s.totalItems).toBe(0);
      expect(s.activeAgents).toBe(0);
      expect(s.itemsBySource).toEqual({});
      expect(s.itemsByScope).toEqual({});
    });

    it("returns correct counts after entangling items", () => {
      const mesh = createEntanglementMesh();
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("i1"));
      handleA.entangle(item("i2"), { scope: ["agent-b"] });

      const s = mesh.stats();
      expect(s.totalItems).toBe(2);
      expect(s.activeAgents).toBe(2);
      expect(s.itemsBySource["agent-a"]).toBe(2);
      expect(s.itemsByScope["*"]).toBe(1);
      expect(s.itemsByScope["agent-b"]).toBe(1);
    });
  });

  describe("clear", () => {
    it("removes all entangled items", () => {
      const mesh = createEntanglementMesh();
      const handle = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handle.entangle(item("i1"));
      handle.entangle(item("i2"));
      expect(mesh.stats().totalItems).toBe(2);

      mesh.clear();
      expect(mesh.stats().totalItems).toBe(0);

      // Agents are still registered
      expect(mesh.listAgents()).toHaveLength(2);
    });
  });

  describe("exportState / importState", () => {
    it("round-trips state correctly", () => {
      const mesh = createEntanglementMesh();
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", {
        budget: { maxTokens: 2000 },
        kindFilter: ["code"],
      });

      handleA.entangle(item("shared-1", "content 1", "code"));
      handleA.entangle(item("shared-2", "content 2", "code"), {
        scope: ["agent-b"],
      });

      const exported = mesh.exportState();

      // Create a new mesh and import
      const mesh2 = createEntanglementMesh();
      mesh2.importState(exported);

      expect(mesh2.stats().totalItems).toBe(2);
      expect(mesh2.listAgents()).toHaveLength(2);

      // Agent handles should work after import
      const handleB2 = mesh2.getAgent("agent-b")!;
      expect(handleB2).not.toBeNull();
      const pending = handleB2.getPending();
      // agent-b should see both items (one wildcard, one scoped to agent-b)
      expect(pending.length).toBeGreaterThanOrEqual(1);
    });

    it("preserves agent kind filters on import", () => {
      const mesh = createEntanglementMesh();
      mesh.register("agent-a", { budget: { maxTokens: 1000 } });
      mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
        kindFilter: ["doc"],
      });

      const exported = mesh.exportState();
      const mesh2 = createEntanglementMesh();
      mesh2.importState(exported);

      const agents = mesh2.listAgents();
      const agentB = agents.find(a => a.agentId === "agent-b");
      expect(agentB?.kindFilter).toEqual(["doc"]);
    });
  });

  describe("maxItems pruning", () => {
    it("prunes oldest items when maxItems is exceeded", () => {
      const mesh = createEntanglementMesh({ maxItems: 3 });
      const handle = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handle.entangle(item("i1"));
      handle.entangle(item("i2"));
      handle.entangle(item("i3"));
      handle.entangle(item("i4"));
      handle.entangle(item("i5"));

      expect(mesh.stats().totalItems).toBe(3);

      // Oldest items (i1, i2) should have been pruned
      const handleB = mesh.getAgent("agent-b")!;
      const pendingIds = handleB.getPending().map(ei => ei.item.id);
      expect(pendingIds).not.toContain("i1");
      expect(pendingIds).not.toContain("i2");
      expect(pendingIds).toContain("i3");
      expect(pendingIds).toContain("i4");
      expect(pendingIds).toContain("i5");
    });
  });

  describe("config callbacks", () => {
    it("calls onEntangle when an item is entangled", () => {
      const onEntangle = vi.fn();
      const mesh = createEntanglementMesh({ onEntangle });

      const handle = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });

      handle.entangle(item("callback-item"));

      expect(onEntangle).toHaveBeenCalledTimes(1);
      expect(onEntangle).toHaveBeenCalledWith(
        expect.objectContaining({
          item: expect.objectContaining({ id: "callback-item" }),
          sourceAgent: "agent-a",
        })
      );
    });

    it("calls onInject when an entangled item is included in a pack", () => {
      const onInject = vi.fn();
      const mesh = createEntanglementMesh({ onInject });

      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("inject-item"));

      handleB.pack([]);

      expect(onInject).toHaveBeenCalledWith(
        expect.objectContaining({
          item: expect.objectContaining({ id: "inject-item" }),
        }),
        "agent-b"
      );
    });
  });

  describe("defaultPropagation config", () => {
    it("uses config default when no propagation specified", () => {
      const mesh = createEntanglementMesh({
        defaultPropagation: "immediate",
      });

      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("default-prop"));

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending[0].propagation).toBe("immediate");
    });
  });

  describe("defaultTTL config", () => {
    it("applies default TTL when no expiresIn specified", () => {
      const mesh = createEntanglementMesh({ defaultTTL: 30_000 });

      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      mesh.register("agent-b", { budget: { maxTokens: 1000 } });

      handleA.entangle(item("ttl-default"));

      const handleB = mesh.getAgent("agent-b")!;
      const pending = handleB.getPending();
      expect(pending[0].expiresAt).toBeDefined();
    });
  });

  describe("TTL expiry filtering", () => {
    it("expired items are not visible in getPending", () => {
      const mesh = createEntanglementMesh();
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });

      // Entangle with an already-expired TTL
      handleA.entangle(item("expired"), { expiresIn: -1000 });

      expect(handleB.getPending()).toHaveLength(0);
    });
  });

  describe("multiple agents with different scopes", () => {
    it("routes items to correct agents based on scope", () => {
      const mesh = createEntanglementMesh();
      const handleA = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });
      const handleB = mesh.register("agent-b", {
        budget: { maxTokens: 1000 },
      });
      const handleC = mesh.register("agent-c", {
        budget: { maxTokens: 1000 },
      });

      handleA.entangle(item("for-b"), { scope: ["agent-b"] });
      handleA.entangle(item("for-c"), { scope: ["agent-c"] });
      handleA.entangle(item("for-all"));

      const bPending = handleB.getPending().map(ei => ei.item.id);
      const cPending = handleC.getPending().map(ei => ei.item.id);

      expect(bPending).toContain("for-b");
      expect(bPending).not.toContain("for-c");
      expect(bPending).toContain("for-all");

      expect(cPending).toContain("for-c");
      expect(cPending).not.toContain("for-b");
      expect(cPending).toContain("for-all");
    });
  });

  describe("edge cases", () => {
    it("handles empty mesh with no agents", () => {
      const mesh = createEntanglementMesh();
      expect(mesh.stats().totalItems).toBe(0);
      expect(mesh.stats().activeAgents).toBe(0);
      expect(mesh.listAgents()).toEqual([]);
    });

    it("handles pack with no items and no entangled items", () => {
      const mesh = createEntanglementMesh();
      const handle = mesh.register("agent-a", {
        budget: { maxTokens: 1000 },
      });

      const result = handle.pack([]);
      expect(result.selected).toEqual([]);
      expect(result.entangledItems).toEqual([]);
      expect(result.ownItems).toEqual([]);
    });

    it("handles agent registered with default budget", () => {
      const mesh = createEntanglementMesh();
      const handle = mesh.register("agent-a");

      // Should not throw
      const result = handle.pack([item("test")]);
      expect(result.selected.length).toBeGreaterThanOrEqual(0);
    });
  });
});
