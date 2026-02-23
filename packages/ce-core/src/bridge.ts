import type { MemoryItem, ContextItem } from "./types.js";

export interface BridgeOptions {
  /** Base priority for all memory items (default: 5) */
  priority?: number;
  /** Reference time for recency calculation (default: Date.now()) */
  now?: number;
  /** Half-life in seconds for recency decay (default: 3600 = 1 hour) */
  recencyHalfLife?: number;
  /** Optional kind tag */
  kind?: string;
}

/**
 * Convert a MemoryItem to a ContextItem with proper scoring fields.
 *
 * Maps salience to metadata.salience (used by the scorer),
 * and computes recency from createdAt using exponential decay.
 *
 * @example
 * ```ts
 * const memories = await store.query({ limit: 20 });
 * const items = memories.map(m => toContextItem(m));
 * const packed = await pack(items, { maxTokens: 4000 });
 * ```
 */
export function toContextItem(
  memory: MemoryItem,
  options?: BridgeOptions,
): ContextItem {
  const now = options?.now ?? Date.now();
  const halfLife = options?.recencyHalfLife ?? 3600;
  const basePriority = options?.priority ?? 5;

  // Compute recency as exponential decay from createdAt
  const ageSeconds = (now - new Date(memory.createdAt).getTime()) / 1000;
  const recency = Math.pow(0.5, ageSeconds / halfLife) * 10; // 0-10 scale

  return {
    id: memory.id,
    content: memory.content,
    kind: options?.kind ?? "memory",
    priority: basePriority,
    recency: Math.round(recency * 100) / 100,
    metadata: {
      ...memory.metadata,
      salience: memory.salience ?? 1.0,
      createdAt: memory.createdAt,
      ...(memory.updatedAt ? { updatedAt: memory.updatedAt } : {}),
    },
  };
}

/**
 * Convert an array of MemoryItems to ContextItems.
 */
export function memoryToContext(
  memories: MemoryItem[],
  options?: BridgeOptions,
): ContextItem[] {
  return memories.map(m => toContextItem(m, options));
}
