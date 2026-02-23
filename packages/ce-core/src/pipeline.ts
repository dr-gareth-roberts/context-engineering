/**
 * Composable Context Pipeline
 *
 * A fluent builder API that chains context engineering operations
 * into a single, readable pipeline. This is the primary DX surface
 * for the library — it composes all the individual pieces.
 *
 * @example
 * ```ts
 * import { pipeline } from "ce-core";
 *
 * const result = pipeline({ maxTokens: 8000 })
 *   .add(systemPrompt, toolDefs)
 *   .addMany(ragResults, { kind: "retrieval" })
 *   .allocate([
 *     { kind: "system", targetRatio: 0.15, minTokens: 500 },
 *     { kind: "retrieval", targetRatio: 0.50 },
 *     { kind: "conversation", targetRatio: 0.35 },
 *   ])
 *   .cacheTopology({ provider: "anthropic" })
 *   .qualityGate({ minOverall: 0.7 })
 *   .build();
 *
 * console.log(result.selected);    // packed, placed, cache-optimized items
 * console.log(result.totalTokens); // total tokens used
 * console.log(result.quality);     // quality metrics
 * console.log(result.cacheKey);    // stable prefix cache key
 * ```
 */

import type { Budget, ContextItem, ContextPack, PackOptions, ScoringWeights } from "./types.js";
import type { MemoryItem } from "./types.js";
import { pack } from "./pack.js";
import { estimateTokens } from "./estimate.js";
import { memoryToContext, type BridgeOptions } from "./bridge.js";
import { placeItems, type PlacementStrategy } from "./placement.js";
import { analyzeContext, type ContextQuality } from "./quality.js";
import {
  packWithCacheTopology,
  type CacheConfig,
  type CacheAwarePack,
} from "./cache-topology.js";
import {
  packWithAllocation,
  type KindAllocation,
  type AllocatedPack,
} from "./allocation.js";
import {
  createSession,
  type ContextSession,
  type SessionDelta,
} from "./session.js";

/**
 * Result of a pipeline build.
 */
export interface PipelineResult {
  /** Selected context items, ordered for delivery */
  selected: ContextItem[];
  /** Items that were dropped due to budget */
  dropped: ContextItem[];
  /** Total tokens in selected items */
  totalTokens: number;
  /** Budget used */
  budget: Budget;
  /** Quality metrics (if quality gate was used) */
  quality?: ContextQuality;
  /** Cache key (if cache topology was used) */
  cacheKey?: string;
  /** Cache efficiency 0-1 (if cache topology was used) */
  cacheEfficiency?: number;
  /** Cacheable tokens (if cache topology was used) */
  cacheableTokens?: number;
  /** Session delta (if session was used) */
  delta?: SessionDelta | null;
  /** Per-kind allocation breakdown (if allocate was used) */
  allocations?: Record<string, unknown>;
  /** Allocation efficiency 0-1 (if allocate was used) */
  allocationEfficiency?: number;
  /** Number of input items before packing */
  inputCount: number;
  /** Pipeline stages that were applied */
  stages: string[];
}

/**
 * A composable pipeline for context engineering.
 *
 * Methods can be chained in any order. The pipeline resolves
 * at `.build()` time, applying stages in the correct order
 * regardless of how they were specified.
 */
export class ContextPipeline {
  private budget: Budget;
  private items: ContextItem[] = [];
  private packOptions: PackOptions = {};

  // Stage configs (applied in order at build time)
  private allocationConfig?: KindAllocation[];
  private cacheTopologyConfig?: CacheConfig;
  private placementConfig?: { strategy?: PlacementStrategy; model?: string };
  private qualityConfig?: { minOverall?: number; warn?: boolean };
  private sessionInstance?: ContextSession;
  private stagesApplied: string[] = [];

  constructor(budget: Budget | number) {
    this.budget = typeof budget === "number"
      ? { maxTokens: budget }
      : budget;
  }

  /**
   * Add one or more context items directly.
   */
  add(...items: ContextItem[]): this {
    this.items.push(...items);
    return this;
  }

  /**
   * Add many items with optional default properties.
   */
  addMany(items: ContextItem[], defaults?: Partial<ContextItem>): this {
    for (const item of items) {
      this.items.push({ ...defaults, ...item } as ContextItem);
    }
    return this;
  }

  /**
   * Bridge memory items into context items and add them.
   */
  addMemories(memories: MemoryItem[], options?: BridgeOptions): this {
    const contextItems = memoryToContext(memories, options);
    this.items.push(...contextItems);
    this.stagesApplied.push("bridge");
    return this;
  }

  /**
   * Configure kind-aware budget allocation.
   * Applied during build to distribute budget across kinds.
   */
  allocate(allocations: KindAllocation[]): this {
    this.allocationConfig = allocations;
    return this;
  }

  /**
   * Configure cache-topology-aware packing.
   * Orders items to maximize prefix cache hits.
   */
  cacheTopology(config?: CacheConfig): this {
    this.cacheTopologyConfig = config ?? {};
    return this;
  }

  /**
   * Configure attention-aware placement.
   * Reorders items based on model attention patterns.
   */
  place(strategy?: PlacementStrategy, model?: string): this {
    this.placementConfig = { strategy, model };
    return this;
  }

  /**
   * Add a quality gate.
   * If minOverall is set and quality is below threshold, drops
   * lowest-quality items until the threshold is met.
   */
  qualityGate(config?: { minOverall?: number; warn?: boolean }): this {
    this.qualityConfig = config ?? {};
    return this;
  }

  /**
   * Attach a session for differential context tracking.
   * The pipeline will set items on the session and compile through it.
   */
  session(session: ContextSession): this {
    this.sessionInstance = session;
    return this;
  }

  /**
   * Set scoring weights for item prioritization.
   */
  weights(weights: ScoringWeights): this {
    this.packOptions.weights = weights;
    return this;
  }

  /**
   * Set pack options.
   */
  options(options: PackOptions): this {
    this.packOptions = { ...this.packOptions, ...options };
    return this;
  }

  /**
   * Build the pipeline and return the result.
   *
   * Stages are applied in this order:
   * 1. Allocation (if configured) — distribute budget by kind
   * 2. Cache topology (if configured) — partition for cache reuse
   * 3. Standard pack (if no allocation/topology) — greedy by score
   * 4. Placement (if configured) — reorder for attention patterns
   * 5. Quality gate (if configured) — analyze and filter
   * 6. Session (if configured) — compute delta from previous
   */
  build(): PipelineResult {
    const inputCount = this.items.length;
    const stages: string[] = [...this.stagesApplied];

    // Ensure all items have token estimates
    const items = this.items.map(item => ({
      ...item,
      tokens: item.tokens ?? estimateTokens(item.content, {
        estimator: this.packOptions.tokenEstimator,
      }),
    }));

    let selected: ContextItem[];
    let dropped: ContextItem[];
    let totalTokens: number;
    let cacheKey: string | undefined;
    let cacheEfficiency: number | undefined;
    let cacheableTokens: number | undefined;
    let allocations: Record<string, unknown> | undefined;
    let allocationEfficiency: number | undefined;

    // Stage 1: Pack (allocation → cache topology → standard)
    if (this.allocationConfig) {
      stages.push("allocate");
      const result = packWithAllocation(
        items,
        this.budget,
        this.allocationConfig,
        this.packOptions,
      );
      selected = result.selected;
      dropped = result.dropped;
      totalTokens = result.totalTokens;
      allocations = result.allocations as unknown as Record<string, unknown>;
      allocationEfficiency = result.allocationEfficiency;

      // If also cache topology, reorder the selected items
      if (this.cacheTopologyConfig) {
        stages.push("cacheTopology");
        const cacheResult = packWithCacheTopology(
          selected,
          { maxTokens: totalTokens + 100 }, // generous budget since already packed
          this.packOptions,
          this.cacheTopologyConfig,
        );
        selected = cacheResult.selected;
        cacheKey = cacheResult.cacheKey;
        cacheEfficiency = cacheResult.cacheEfficiency;
        cacheableTokens = cacheResult.cacheableTokens;
      }
    } else if (this.cacheTopologyConfig) {
      stages.push("cacheTopology");
      const result = packWithCacheTopology(
        items,
        this.budget,
        this.packOptions,
        this.cacheTopologyConfig,
      );
      selected = result.selected;
      dropped = result.dropped;
      totalTokens = result.totalTokens;
      cacheKey = result.cacheKey;
      cacheEfficiency = result.cacheEfficiency;
      cacheableTokens = result.cacheableTokens;
    } else {
      stages.push("pack");
      const result = pack(items, this.budget, this.packOptions);
      selected = result.selected;
      dropped = result.dropped;
      totalTokens = result.totalTokens;
    }

    // Stage 2: Placement
    if (this.placementConfig) {
      stages.push("place");
      selected = placeItems(
        selected,
        this.placementConfig.strategy,
        this.placementConfig.model,
      );
    }

    // Stage 3: Quality gate
    let quality: ContextQuality | undefined;
    if (this.qualityConfig) {
      stages.push("quality");
      quality = analyzeContext(selected);

      if (
        this.qualityConfig.minOverall !== undefined &&
        quality.overall < this.qualityConfig.minOverall &&
        selected.length > 1
      ) {
        // Drop items with lowest individual contribution until quality improves
        // Simple approach: remove items one at a time from the end
        while (
          selected.length > 1 &&
          quality.overall < this.qualityConfig.minOverall
        ) {
          const removed = selected.pop()!;
          dropped.push(removed);
          totalTokens -= removed.tokens ?? 0;
          quality = analyzeContext(selected);
        }
      }
    }

    // Stage 4: Session tracking
    let delta: SessionDelta | null | undefined;
    if (this.sessionInstance) {
      stages.push("session");
      this.sessionInstance.setItems(selected);
      const sessionResult = this.sessionInstance.compile();
      delta = sessionResult.delta;
    }

    return {
      selected,
      dropped,
      totalTokens,
      budget: this.budget,
      quality,
      cacheKey,
      cacheEfficiency,
      cacheableTokens,
      delta,
      allocations,
      allocationEfficiency,
      inputCount,
      stages,
    };
  }
}

/**
 * Create a new context pipeline.
 *
 * @param budget - Token budget (number or Budget object)
 * @returns A chainable ContextPipeline
 *
 * @example
 * ```ts
 * // Simple usage
 * const result = pipeline(4096)
 *   .add(systemPrompt, query)
 *   .build();
 *
 * // Full pipeline
 * const result = pipeline({ maxTokens: 8000, reserveTokens: 500 })
 *   .add(systemPrompt)
 *   .addMemories(await store.search("topic"), { kind: "memory" })
 *   .addMany(ragDocs, { kind: "retrieval" })
 *   .allocate([
 *     { kind: "system", targetRatio: 0.15 },
 *     { kind: "memory", targetRatio: 0.20 },
 *     { kind: "retrieval", targetRatio: 0.65 },
 *   ])
 *   .cacheTopology({ provider: "anthropic" })
 *   .qualityGate({ minOverall: 0.6 })
 *   .session(mySession)
 *   .build();
 * ```
 */
export function pipeline(budget: Budget | number): ContextPipeline {
  return new ContextPipeline(budget);
}
