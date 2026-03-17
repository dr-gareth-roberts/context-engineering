/**
 * Differential Context Sessions
 *
 * Stateful session manager that tracks what was sent in previous requests
 * and computes minimal diffs between turns. Combined with cache-topology
 * packing, this maximizes prefix cache reuse across API calls.
 *
 * Research: ACE framework showed 83.6% lower token costs with incremental
 * delta updates compared to full recomputation baselines.
 */

import type { Budget, ContextItem, PackOptions } from "./types.js";
import { pack } from "./pack.js";
import { estimateTokens } from "./estimate.js";
import { hash64 } from "./hash.js";

/**
 * A manifest entry tracking an item's position and content hash.
 */
interface ManifestEntry {
  id: string;
  contentHash: string;
  tokens: number;
  position: number;
}

/**
 * Delta between two session states.
 */
export interface SessionDelta {
  /** Items added since last compile */
  added: ContextItem[];
  /** Item IDs removed since last compile */
  removedIds: string[];
  /** Items whose content changed */
  changed: ContextItem[];
  /** Number of items unchanged */
  keptCount: number;
  /** Tokens that changed (added + removed + changed) */
  deltaTokens: number;
  /** Tokens reusable from the previous request's KV cache */
  reusableTokens: number;
  /** Fraction of tokens reusable (0-1) */
  reuseRatio: number;
}

/**
 * Result from session compile.
 */
export interface SessionPack {
  /** All selected items for the current request */
  selected: ContextItem[];
  /** Items that were dropped */
  dropped: ContextItem[];
  /** Total tokens in the compiled context */
  totalTokens: number;
  /** Delta from the previous compile (null on first compile) */
  delta: SessionDelta | null;
  /** Stable cache key (hash of unchanged prefix items) */
  cacheKey: string;
  /** Cumulative compile count */
  compileCount: number;
}

function unchangedPrefix(
  previous: ManifestEntry[],
  current: ManifestEntry[]
): ManifestEntry[] {
  const prefix: ManifestEntry[] = [];
  const maxLength = Math.min(previous.length, current.length);
  for (let i = 0; i < maxLength; i++) {
    const prev = previous[i];
    const curr = current[i];
    if (prev.id !== curr.id || prev.contentHash !== curr.contentHash) break;
    prefix.push(curr);
  }
  return prefix;
}

/**
 * A stateful context session that tracks changes between compiles.
 *
 * On each compile(), it packs the current items and computes the diff
 * from the previous compile. This enables:
 * - Tracking how much context actually changes between turns
 * - Computing cache reuse ratios for cost estimation
 * - Identifying stable prefixes that benefit from KV cache
 *
 * @example
 * ```ts
 * const session = createSession({ maxTokens: 8000 });
 *
 * // Turn 1
 * session.setItems([systemPrompt, doc1, doc2, query1]);
 * const r1 = session.compile();
 * // r1.delta is null (first compile)
 *
 * // Turn 2 — only query changed
 * session.setItems([systemPrompt, doc1, doc2, query2]);
 * const r2 = session.compile();
 * // r2.delta.reuseRatio ≈ 0.85 (most tokens cached)
 * ```
 */
export interface ContextSession {
  /** Replace the current item set */
  setItems(items: ContextItem[]): void;
  /** Add items to the current set */
  addItems(items: ContextItem[]): void;
  /** Remove items by ID */
  removeItems(ids: string[]): void;
  /** Compile the current context, computing delta from previous */
  compile(options?: PackOptions): SessionPack;
  /** Get the current item count (before packing) */
  itemCount(): number;
  /** Get the number of compiles performed */
  getCompileCount(): number;
  /** Reset the session */
  clear(): void;
}

export interface SessionOptions {
  /** Token budget */
  budget: Budget;
  /** Default pack options */
  packOptions?: PackOptions;
}

/**
 * Create a stateful context session that tracks changes between compiles.
 *
 * @param options - Session configuration including token budget and default pack options
 * @returns A ContextSession instance
 */
export function createSession(options: SessionOptions): ContextSession {
  const budget = options.budget;
  const defaultPackOptions = options.packOptions ?? {};

  let currentItems: ContextItem[] = [];
  let previousManifest: ManifestEntry[] = [];
  let compileCount = 0;

  function setItems(items: ContextItem[]): void {
    currentItems = [...items];
  }

  function addItems(items: ContextItem[]): void {
    // Deduplicate by id — new items override existing
    const existing = new Map(currentItems.map(i => [i.id, i]));
    for (const item of items) {
      existing.set(item.id, item);
    }
    currentItems = Array.from(existing.values());
  }

  function removeItems(ids: string[]): void {
    const removeSet = new Set(ids);
    currentItems = currentItems.filter(i => !removeSet.has(i.id));
  }

  function compile(packOptions?: PackOptions): SessionPack {
    const opts = { ...defaultPackOptions, ...packOptions };
    const estimator = opts.tokenEstimator;

    // Pack current items
    const packed = pack(currentItems, budget, opts);

    // Build manifest for current compile
    const currentManifest: ManifestEntry[] = packed.selected.map((item, i) => ({
      id: item.id,
      contentHash: hash64(item.content),
      tokens: item.tokens ?? estimateTokens(item.content, { estimator }),
      position: i,
    }));

    // Compute delta from previous
    let delta: SessionDelta | null = null;

    if (compileCount > 0) {
      const prevMap = new Map(previousManifest.map(e => [e.id, e]));
      const currMap = new Map(currentManifest.map(e => [e.id, e]));
      const reusablePrefix = unchangedPrefix(previousManifest, currentManifest);
      const reusablePrefixIds = new Set(reusablePrefix.map(entry => entry.id));

      const added: ContextItem[] = [];
      const changed: ContextItem[] = [];
      const removedIds: string[] = [];
      let keptCount = 0;
      let addedTokens = 0;
      let removedTokens = 0;
      let changedTokens = 0;
      let reusableTokens = 0;

      // Build a map from id -> item for O(1) lookups
      const selectedMap = new Map(packed.selected.map(i => [i.id, i]));

      // Find added and changed
      for (const entry of currentManifest) {
        const prev = prevMap.get(entry.id);
        if (!prev) {
          // New item
          const item = selectedMap.get(entry.id);
          if (item) added.push(item);
          addedTokens += entry.tokens;
        } else if (prev.contentHash !== entry.contentHash) {
          // Content changed
          const item = selectedMap.get(entry.id);
          if (item) changed.push(item);
          changedTokens += entry.tokens;
        } else {
          // Unchanged
          keptCount++;
          if (reusablePrefixIds.has(entry.id)) {
            reusableTokens += entry.tokens;
          }
        }
      }

      // Find removed
      for (const entry of previousManifest) {
        if (!currMap.has(entry.id)) {
          removedIds.push(entry.id);
          removedTokens += entry.tokens;
        }
      }

      const deltaTokens = addedTokens + removedTokens + changedTokens;
      const totalPrev = previousManifest.reduce((s, e) => s + e.tokens, 0);

      delta = {
        added,
        removedIds,
        changed,
        keptCount,
        deltaTokens,
        reusableTokens,
        reuseRatio:
          totalPrev > 0
            ? Math.round((reusableTokens / totalPrev) * 1000) / 1000
            : 0,
      };
    }

    // Generate cache key from unchanged items
    const prefix = unchangedPrefix(previousManifest, currentManifest);
    const cacheKey = hash64(
      prefix
        .map(entry => `${entry.position}:${entry.id}:${entry.contentHash}`)
        .join(",") || "empty"
    );

    // Update state for next compile
    previousManifest = currentManifest;
    compileCount++;

    return {
      selected: packed.selected,
      dropped: packed.dropped,
      totalTokens: packed.totalTokens,
      delta,
      cacheKey,
      compileCount,
    };
  }

  function itemCount(): number {
    return currentItems.length;
  }

  function getCompileCount(): number {
    return compileCount;
  }

  function clear(): void {
    currentItems = [];
    previousManifest = [];
    compileCount = 0;
  }

  return {
    setItems,
    addItems,
    removeItems,
    compile,
    itemCount,
    getCompileCount,
    clear,
  };
}
