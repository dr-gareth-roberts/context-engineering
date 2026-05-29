import type {
  ContextItem,
  Budget,
  PackOptions,
  ContextPack,
} from "@context-engineering/core";
import { pack } from "@context-engineering/core";
import type {
  AgentHandle,
  AgentRegistration,
  EntangledItem,
  EntangleOptions,
  MeshConfig,
  PropagationPolicy,
} from "./types.js";
import { filterForAgent } from "./propagation.js";

/** Internal mesh store shared between all agent handles */
export interface MeshStore {
  items: EntangledItem[];
  agents: Map<string, AgentRegistration>;
  handles: Map<string, AgentHandle>;
  config: Required<Pick<MeshConfig, "maxItems">> & MeshConfig;
}

/**
 * Create an AgentHandle bound to a specific agent and mesh store.
 */
export function createAgentHandle(
  registration: AgentRegistration,
  store: MeshStore
): AgentHandle {
  const agentId = registration.agentId;

  // Track acknowledged item IDs for "immediate" propagation
  const acknowledged = new Set<string>();

  const handle: AgentHandle = {
    get agentId(): string {
      return agentId;
    },

    entangle(item: ContextItem, options?: EntangleOptions): void {
      const propagation: PropagationPolicy =
        options?.propagation ?? store.config.defaultPropagation ?? "next-pack";

      const now = Date.now();

      // Apply priority override if specified
      const entangledContextItem: ContextItem =
        options?.priority !== undefined
          ? { ...item, priority: options.priority }
          : item;

      const entangledItem: EntangledItem = {
        item: entangledContextItem,
        sourceAgent: agentId,
        propagation,
        scope: options?.scope ?? "*",
        entangledAt: now,
        expiresAt:
          options?.expiresIn !== undefined
            ? now + options.expiresIn
            : store.config.defaultTTL !== undefined
              ? now + store.config.defaultTTL
              : undefined,
        metadata: options?.metadata,
      };

      store.items.push(entangledItem);

      // Prune oldest items if over maxItems
      if (store.items.length > store.config.maxItems) {
        const excess = store.items.length - store.config.maxItems;
        store.items.splice(0, excess);
      }

      // Fire onEntangle callback
      store.config.onEntangle?.(entangledItem);
    },

    pack(
      items: ContextItem[],
      budget?: Budget,
      options?: PackOptions
    ): ContextPack & {
      entangledItems: EntangledItem[];
      ownItems: ContextItem[];
    } {
      const agentReg = store.agents.get(agentId);
      const effectiveBudget = budget ?? agentReg?.budget ?? { maxTokens: 4096 };
      const kindFilter = agentReg?.kindFilter;

      // Get entangled items intended for this agent (excluding on-demand)
      const pending = filterForAgent(store.items, agentId, kindFilter, {
        acknowledged,
        forPack: true,
      });

      // Convert entangled items to ContextItem[] for packing
      const entangledContextItems = pending.map(ei => ei.item);

      // Merge own items with entangled items (own items first for priority)
      const allItems = [...items, ...entangledContextItems];

      // Pack using ce-core
      const result = pack(allItems, effectiveBudget, options ?? {});

      // Fire onInject for each entangled item that was selected
      const selectedIds = new Set(result.selected.map(s => s.id));
      for (const ei of pending) {
        if (selectedIds.has(ei.item.id)) {
          store.config.onInject?.(ei, agentId);
        }
      }

      return {
        ...result,
        entangledItems: pending.filter(ei => selectedIds.has(ei.item.id)),
        ownItems: items.filter(i => selectedIds.has(i.id)),
      };
    },

    getPending(): EntangledItem[] {
      const agentReg = store.agents.get(agentId);
      return filterForAgent(store.items, agentId, agentReg?.kindFilter, {
        acknowledged,
        forPack: false,
      });
    },

    acknowledge(...itemIds: string[]): void {
      for (const id of itemIds) {
        acknowledged.add(id);
      }
      // Drop acknowledged IDs whose items have been pruned from the store —
      // they are never queried again (filterForAgent only iterates store.items).
      if (acknowledged.size > store.items.length) {
        const live = new Set(store.items.map(ei => ei.item.id));
        for (const id of acknowledged) {
          if (!live.has(id)) {
            acknowledged.delete(id);
          }
        }
      }
    },

    unregister(): void {
      store.agents.delete(agentId);
      store.handles.delete(agentId);
    },
  };

  return handle;
}
