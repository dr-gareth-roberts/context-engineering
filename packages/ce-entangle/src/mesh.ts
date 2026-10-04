import type {
  AgentHandle,
  AgentRegistration,
  EntanglementMesh,
  MeshConfig,
  MeshState,
  MeshStats,
} from "./types.js";
import { createAgentHandle, type MeshStore } from "./agent-handle.js";

const DEFAULT_MAX_ITEMS = 1000;

function deepClone<T>(value: T): T {
  if (typeof globalThis.structuredClone === "function") {
    return globalThis.structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

/**
 * Create an entanglement mesh — a shared fabric for multi-agent context sharing.
 *
 * Agents register with the mesh to publish and receive context items through
 * scoped pub/sub at the packing layer.
 */
export function createEntanglementMesh(config?: MeshConfig): EntanglementMesh {
  const store: MeshStore = {
    items: [],
    agents: new Map(),
    handles: new Map(),
    config: {
      maxItems: config?.maxItems ?? DEFAULT_MAX_ITEMS,
      ...config,
    },
  };

  const mesh: EntanglementMesh = {
    register(
      agentId: string,
      options?: Omit<AgentRegistration, "agentId">
    ): AgentHandle {
      if (store.agents.has(agentId)) {
        throw new Error(`Agent "${agentId}" is already registered in the mesh`);
      }

      const registration: AgentRegistration = {
        agentId,
        budget: options?.budget ?? { maxTokens: 4096 },
        kindFilter: options?.kindFilter,
      };

      store.agents.set(agentId, registration);

      const handle = createAgentHandle(registration, store);
      store.handles.set(agentId, handle);

      return handle;
    },

    getAgent(agentId: string): AgentHandle | null {
      return store.handles.get(agentId) ?? null;
    },

    listAgents(): AgentRegistration[] {
      return deepClone(Array.from(store.agents.values()));
    },

    stats(): MeshStats {
      const itemsBySource: Record<string, number> = {};
      const itemsByScope: Record<string, number> = {};

      for (const item of store.items) {
        itemsBySource[item.sourceAgent] =
          (itemsBySource[item.sourceAgent] ?? 0) + 1;

        if (item.scope === "*") {
          itemsByScope["*"] = (itemsByScope["*"] ?? 0) + 1;
        } else {
          for (const target of item.scope) {
            itemsByScope[target] = (itemsByScope[target] ?? 0) + 1;
          }
        }
      }

      return {
        totalItems: store.items.length,
        activeAgents: store.agents.size,
        itemsBySource,
        itemsByScope,
      };
    },

    clear(): void {
      store.items.length = 0;
    },

    exportState(): MeshState {
      return {
        items: deepClone(store.items),
        agents: deepClone(Array.from(store.agents.values())),
      };
    },

    importState(state: MeshState): void {
      store.items.length = 0;
      store.items.push(...deepClone(state.items));

      // Re-register agents from imported state (skip already registered ones)
      for (const reg of state.agents) {
        if (!store.agents.has(reg.agentId)) {
          const registration = deepClone(reg);
          store.agents.set(registration.agentId, registration);
          const handle = createAgentHandle(registration, store);
          store.handles.set(reg.agentId, handle);
        }
      }
    },
  };

  return mesh;
}
