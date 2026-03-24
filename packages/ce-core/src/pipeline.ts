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

import type {
  Budget,
  ContextItem,
  ContextPack,
  EmbeddingProvider,
  PackOptions,
  QueryInput,
  ScoringWeights,
} from "./types.js";
import type { MemoryItem } from "./types.js";
import { pack, packAsync } from "./pack.js";
import { estimateTokens } from "./estimate.js";
import { memoryToContext, type BridgeOptions } from "./bridge.js";
import { placeItems, type PlacementStrategy } from "./placement.js";
import { analyzeContext, type ContextQuality } from "./quality.js";
import {
  packWithCacheTopology,
  packWithCacheTopologyAsync,
  type CacheConfig,
  type CacheAwarePack,
} from "./cache-topology.js";
import {
  packWithAllocation,
  packWithAllocationAsync,
  type KindAllocation,
  type AllocatedPack,
} from "./allocation.js";
import { type ContextSession, type SessionDelta } from "./session.js";
import {
  toMessages,
  type PromptMessages,
  type PromptTemplateConfig,
} from "./template.js";
import type { MaybeAsync } from "./maybe-async.js";
import { chain } from "./maybe-async.js";

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
  /** Prompt messages (if template was used) */
  messages?: PromptMessages;
  /** Number of input items before packing */
  inputCount: number;
  /** Pipeline stages that were applied */
  stages: string[];
}

/** Function signatures for the sync/async pack variants. */
type PackFn = (
  items: ContextItem[],
  budget: Budget,
  options: PackOptions
) => MaybeAsync<ContextPack>;

type AllocPackFn = (
  items: ContextItem[],
  budget: Budget,
  allocations: KindAllocation[],
  options: PackOptions
) => MaybeAsync<AllocatedPack>;

type CachePackFn = (
  items: ContextItem[],
  budget: Budget,
  options: PackOptions,
  cacheConfig: CacheConfig
) => MaybeAsync<CacheAwarePack>;

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
  private queryConfig?: {
    query: QueryInput;
    embeddingProvider?: EmbeddingProvider;
  };
  private templateConfig?: PromptTemplateConfig;
  private stagesApplied: string[] = [];

  constructor(budget: Budget | number) {
    this.budget = typeof budget === "number" ? { maxTokens: budget } : budget;
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
   * Configure prompt templating.
   * When set, the build result includes assembled PromptMessages.
   */
  template(config?: PromptTemplateConfig): this {
    this.templateConfig = config ?? {};
    return this;
  }

  /**
   * Set a query for relevance-aware scoring.
   * When set, items matching the query score higher.
   */
  withQuery(
    query: QueryInput,
    options?: { embeddingProvider?: EmbeddingProvider }
  ): this {
    this.queryConfig = {
      query,
      embeddingProvider: options?.embeddingProvider,
    };
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
   * Apply quality gate: analyze items and drop lowest-scored until threshold met.
   * Mutates selected and dropped arrays in place.
   */
  private applyQualityGate(
    selected: ContextItem[],
    dropped: ContextItem[],
    totalTokens: number
  ): { quality?: ContextQuality; totalTokens: number } {
    if (!this.qualityConfig) return { totalTokens };

    let quality = analyzeContext(selected);

    if (
      this.qualityConfig.minOverall !== undefined &&
      quality.overall < this.qualityConfig.minOverall &&
      selected.length > 1
    ) {
      while (
        selected.length > 1 &&
        quality.overall < this.qualityConfig.minOverall
      ) {
        let minIdx = 0;
        let minScore = selected[0].score ?? 0;
        for (let i = 1; i < selected.length; i++) {
          const s = selected[i].score ?? 0;
          if (s < minScore) {
            minScore = s;
            minIdx = i;
          }
        }
        const [removed] = selected.splice(minIdx, 1);
        dropped.push(removed);
        totalTokens -= removed.tokens ?? 0;
        quality = analyzeContext(selected);
      }
    }

    return { quality, totalTokens };
  }

  /**
   * Shared build implementation using MaybeAsync.
   * The sync path never creates Promises; the async path chains naturally.
   */
  private buildImpl(
    packFn: PackFn,
    allocPackFn: AllocPackFn,
    cachePackFn: CachePackFn
  ): MaybeAsync<PipelineResult> {
    const inputCount = this.items.length;
    const stages: string[] = [...this.stagesApplied];

    // Ensure all items have token estimates
    const items = this.items.map(item => ({
      ...item,
      tokens:
        item.tokens ??
        estimateTokens(item.content, {
          estimator: this.packOptions.tokenEstimator,
        }),
    }));

    // Wire query into pack options
    const packOpts: PackOptions = { ...this.packOptions };
    if (this.queryConfig) {
      stages.push("query");
      packOpts.query = this.queryConfig.query;
      if (this.queryConfig.embeddingProvider) {
        packOpts.embeddingProvider = this.queryConfig.embeddingProvider;
      }
    }

    // Stage 1: Pack (allocation → cache topology → standard)
    let packResult: MaybeAsync<{
      selected: ContextItem[];
      dropped: ContextItem[];
      totalTokens: number;
      cacheKey?: string;
      cacheEfficiency?: number;
      cacheableTokens?: number;
      allocations?: Record<string, unknown>;
      allocationEfficiency?: number;
    }>;

    if (this.allocationConfig) {
      stages.push("allocate");
      const allocConfig = this.allocationConfig;
      const cacheConfig = this.cacheTopologyConfig;

      packResult = chain(
        allocPackFn(items, this.budget, allocConfig, packOpts),
        result => {
          const base = {
            selected: result.selected,
            dropped: result.dropped,
            totalTokens: result.totalTokens,
            allocations: result.allocations as unknown as Record<
              string,
              unknown
            >,
            allocationEfficiency: result.allocationEfficiency,
          };

          if (cacheConfig) {
            stages.push("cacheTopology");
            return chain(
              cachePackFn(
                result.selected,
                { maxTokens: result.totalTokens + 100 },
                packOpts,
                cacheConfig
              ),
              cacheResult => ({
                ...base,
                selected: cacheResult.selected,
                cacheKey: cacheResult.cacheKey,
                cacheEfficiency: cacheResult.cacheEfficiency,
                cacheableTokens: cacheResult.cacheableTokens,
              })
            );
          }

          return base;
        }
      );
    } else if (this.cacheTopologyConfig) {
      stages.push("cacheTopology");
      packResult = chain(
        cachePackFn(items, this.budget, packOpts, this.cacheTopologyConfig),
        result => ({
          selected: result.selected,
          dropped: result.dropped,
          totalTokens: result.totalTokens,
          cacheKey: result.cacheKey,
          cacheEfficiency: result.cacheEfficiency,
          cacheableTokens: result.cacheableTokens,
        })
      );
    } else {
      stages.push("pack");
      packResult = chain(packFn(items, this.budget, packOpts), result => ({
        selected: result.selected,
        dropped: result.dropped,
        totalTokens: result.totalTokens,
      }));
    }

    // Post-pack stages (placement, quality, session, template) are all sync
    return chain(packResult, packed => {
      let { selected, totalTokens } = packed;
      const { dropped } = packed;

      // Stage 2: Placement
      if (this.placementConfig) {
        stages.push("place");
        selected = placeItems(selected, {
          strategy: this.placementConfig.strategy,
          model: this.placementConfig.model,
        });
      }

      // Stage 3: Quality gate
      const qualityResult = this.applyQualityGate(
        selected,
        dropped,
        totalTokens
      );
      const quality = qualityResult.quality;
      totalTokens = qualityResult.totalTokens;
      if (quality) stages.push("quality");

      // Stage 4: Session tracking
      let delta: SessionDelta | null | undefined;
      if (this.sessionInstance) {
        stages.push("session");
        this.sessionInstance.setItems(selected);
        const sessionResult = this.sessionInstance.compile();
        delta = sessionResult.delta;
      }

      // Stage 5: Template
      let promptMessages: PromptMessages | undefined;
      if (this.templateConfig) {
        stages.push("template");
        promptMessages = toMessages(selected, this.templateConfig);
      }

      return {
        selected,
        dropped,
        totalTokens,
        budget: this.budget,
        quality,
        cacheKey: packed.cacheKey,
        cacheEfficiency: packed.cacheEfficiency,
        cacheableTokens: packed.cacheableTokens,
        delta,
        allocations: packed.allocations,
        allocationEfficiency: packed.allocationEfficiency,
        messages: promptMessages,
        inputCount,
        stages,
      };
    });
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
    return this.buildImpl(
      pack,
      packWithAllocation,
      packWithCacheTopology
    ) as PipelineResult;
  }

  /**
   * Async build with full parity to build().
   *
   * Supports all stages including allocation, cache topology, and template.
   * Uses async pack variants that support embedding-based redundancy.
   */
  async buildAsync(): Promise<PipelineResult> {
    return this.buildImpl(
      packAsync,
      packWithAllocationAsync,
      packWithCacheTopologyAsync
    ) as Promise<PipelineResult>;
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
