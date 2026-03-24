import type {
  ContextItem,
  Budget,
  PackOptions,
  ContextPack,
} from "@context-engineering/core";

/** How quickly an entangled item propagates to other agents */
export type PropagationPolicy = "immediate" | "next-pack" | "on-demand";

/** An item published to the mesh */
export interface EntangledItem {
  item: ContextItem;
  sourceAgent: string;
  propagation: PropagationPolicy;
  /** Which agents receive this item. "*" means all agents. */
  scope: string[] | "*";
  entangledAt: number;
  /** Optional TTL — absolute timestamp after which the item expires */
  expiresAt?: number;
  metadata?: Record<string, unknown>;
}

export interface AgentRegistration {
  agentId: string;
  budget: Budget;
  /**
   * Kinds this agent is interested in.
   * If set, only entangled items matching these kinds are injected.
   */
  kindFilter?: string[];
}

export interface AgentHandle {
  /** The agent's ID */
  readonly agentId: string;

  /** Entangle an item — publish it to other agents via the mesh */
  entangle(item: ContextItem, options?: EntangleOptions): void;

  /**
   * Pack this agent's items WITH entangled items from the mesh injected.
   * Returns the standard ContextPack plus metadata about injected items.
   */
  pack(
    items: ContextItem[],
    budget?: Budget,
    options?: PackOptions
  ): ContextPack & {
    entangledItems: EntangledItem[];
    ownItems: ContextItem[];
  };

  /** Get pending entangled items for this agent without packing */
  getPending(): EntangledItem[];

  /** Acknowledge entangled items (removes them from pending for "immediate" policy) */
  acknowledge(...itemIds: string[]): void;

  /** Unregister from the mesh */
  unregister(): void;
}

export interface EntangleOptions {
  propagation?: PropagationPolicy;
  /** Which agents see this item. Default: "*" (all) */
  scope?: string[] | "*";
  /** TTL in milliseconds from the time of entanglement */
  expiresIn?: number;
  /** Override priority for the entangled item */
  priority?: number;
  metadata?: Record<string, unknown>;
}

export interface MeshConfig {
  /** Default propagation policy. Default: "next-pack" */
  defaultPropagation?: PropagationPolicy;
  /** Default TTL for entangled items in ms. Default: undefined (no expiry) */
  defaultTTL?: number;
  /** Max entangled items in the mesh. Oldest pruned first. Default: 1000 */
  maxItems?: number;
  /** Called when an item is entangled */
  onEntangle?: (item: EntangledItem) => void;
  /** Called when an entangled item is injected into a pack */
  onInject?: (item: EntangledItem, targetAgent: string) => void;
}

export interface MeshState {
  items: EntangledItem[];
  agents: AgentRegistration[];
}

export interface MeshStats {
  totalItems: number;
  activeAgents: number;
  itemsBySource: Record<string, number>;
  itemsByScope: Record<string, number>;
}

export interface EntanglementMesh {
  /** Register an agent and get a handle */
  register(
    agentId: string,
    options?: Omit<AgentRegistration, "agentId">
  ): AgentHandle;

  /** Get an existing agent handle */
  getAgent(agentId: string): AgentHandle | null;

  /** List all registered agents */
  listAgents(): AgentRegistration[];

  /** Get mesh statistics */
  stats(): MeshStats;

  /** Clear all entangled items */
  clear(): void;

  /** Export state for persistence */
  exportState(): MeshState;

  /** Import previously exported state */
  importState(state: MeshState): void;
}
