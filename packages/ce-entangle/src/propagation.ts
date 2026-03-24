import type { EntangledItem } from "./types.js";

/**
 * Check whether an entangled item has expired.
 */
export function isExpired(item: EntangledItem, now?: number): boolean {
  if (item.expiresAt === undefined) {
    return false;
  }
  return (now ?? Date.now()) >= item.expiresAt;
}

/**
 * Check whether an entangled item's scope includes the given agent.
 * Items never match their own source agent.
 */
export function matchesScope(item: EntangledItem, agentId: string): boolean {
  if (item.sourceAgent === agentId) {
    return false;
  }
  if (item.scope === "*") {
    return true;
  }
  return item.scope.includes(agentId);
}

/**
 * Check whether an entangled item's kind matches the agent's kind filter.
 * If the agent has no kind filter, all items match.
 */
export function matchesKindFilter(
  item: EntangledItem,
  kindFilter?: string[]
): boolean {
  if (!kindFilter || kindFilter.length === 0) {
    return true;
  }
  const itemKind = item.item.kind;
  if (!itemKind) {
    return false;
  }
  return kindFilter.includes(itemKind);
}

/**
 * Filter entangled items for a specific agent based on scope, kind,
 * expiry, and propagation policy.
 *
 * - "immediate": available right away, persists until acknowledged.
 * - "next-pack": available starting from the next pack() call after entanglement.
 * - "on-demand": never auto-injected into pack(). Only via getPending().
 */
export function filterForAgent(
  items: EntangledItem[],
  agentId: string,
  kindFilter?: string[],
  options?: {
    /** Set of item IDs already acknowledged by this agent */
    acknowledged?: Set<string>;
    /** Only include items injectable into pack (excludes "on-demand") */
    forPack?: boolean;
    now?: number;
  }
): EntangledItem[] {
  const now = options?.now ?? Date.now();
  const acknowledged = options?.acknowledged ?? new Set<string>();
  const forPack = options?.forPack ?? false;

  return items.filter(item => {
    // Expired items are excluded
    if (isExpired(item, now)) {
      return false;
    }

    // Scope must match (also excludes own items)
    if (!matchesScope(item, agentId)) {
      return false;
    }

    // Kind filter
    if (!matchesKindFilter(item, kindFilter)) {
      return false;
    }

    // "on-demand" items are never auto-injected into pack
    if (forPack && item.propagation === "on-demand") {
      return false;
    }

    // "immediate" items that have been acknowledged are excluded
    if (item.propagation === "immediate" && acknowledged.has(item.item.id)) {
      return false;
    }

    return true;
  });
}
