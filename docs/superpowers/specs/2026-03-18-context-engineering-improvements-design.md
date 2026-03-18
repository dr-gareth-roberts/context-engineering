# Context Engineering Toolkit — Improvements Design Spec

**Date:** 2026-03-18
**Status:** Approved
**Scope:** Algorithms, robustness, and new capabilities across TS and Python SDKs

## Overview

Three phases of improvements to the Context Engineering Toolkit, each independently shippable. The work addresses naive relevance scoring, missing input validation, embedding-only redundancy detection, truncation-only compaction, incomplete async pipeline support, and concurrency safety gaps.

**Constraints:**

- Breaking changes are acceptable (pre-1.0, move fast)
- Both TS and Python get all changes (except 3B which is Python-only)
- No backward compatibility shims

---

## Breaking Changes Summary

All breaking changes in one place for migration awareness:

| Item | Change                                                                  | Migration                                                                                             |
| ---- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| 1C   | `RedundancyOptions.provider` renamed to `embeddingProvider`             | Find-and-replace in call sites                                                                        |
| 1C   | `RedundancyOptions.similarityThreshold` renamed to `threshold`          | Find-and-replace                                                                                      |
| 1C   | `strategy: "summarize"` removed from `RedundancyOptions`                | Change to `"recent"` (was already the behavior)                                                       |
| 1C   | Default embedding threshold changed from 0.92 to 0.85                   | Pass explicit `threshold: 0.92` to keep old behavior                                                  |
| 1A   | `computeRelevance` default scoring changes from keyword overlap to BM25 | Existing callers get better scores; pass `scoringMethod: "keyword"` to keep old behavior              |
| 2A   | `Summarizer` type becomes async: returns `Promise<ContextItem \| null>` | Add `async`/`await` to custom summarizer implementations                                              |
| 2A   | New `compileAsync()` method on `ContextManager`                         | Use `compileAsync()` when providing an LLM summarizer; sync `compile()` unchanged for truncation-only |

---

## Prerequisite: EmbeddingProvider Reconciliation

**Problem:** Two `EmbeddingProvider` interfaces exist with incompatible signatures:

- `ce-core/types.ts`: `embed(texts: string[]): Promise<number[][]>`
- `ce-providers/types.ts`: `embed(inputs: string[], options?): Promise<EmbeddingResult>` where `EmbeddingResult = { vectors: number[][]; model: string }`

**Resolution:** The ce-core interface is authoritative (it's what `packAsync` and `eliminateRedundancy` call). Add an adapter in ce-providers:

```ts
// ce-providers/src/embedding-adapter.ts
function adaptEmbeddingProvider(
  provider: CeProvidersEmbeddingProvider
): CoreEmbeddingProvider {
  return {
    embed: async (texts: string[]) => {
      const result = await provider.embed(texts);
      return result.vectors;
    },
  };
}
```

This adapter is created as part of Phase 1C work (first place the mismatch matters). Existing direct users of `packAsync` who pass a ce-providers embedding provider will need to wrap it.

---

## Phase 1: "Better Selection"

### 1A. BM25 Relevance Scoring

**Problem:** `relevance.ts` and `relevance.py` use naive keyword overlap (`found / queryKeywords.length`). All keywords are weighted equally, term frequency is ignored, and the ASCII-only regex `[a-z0-9]+` drops all non-ASCII characters.

**Solution:** Replace keyword overlap with BM25 scoring.

**New module — `bm25.ts` / `bm25.py` in ce-core:**

```ts
// Exported standalone tokenizer — reused by redundancy (1C) and relevance
function unicodeTokenize(text: string): string[];

interface BM25Index {
  add(id: string, text: string): void;
  score(query: string, id: string): number;
  scoreAll(query: string): Map<string, number>;
  readonly documentCount: number;
}

function createBM25Index(options?: {
  k1?: number; // term frequency saturation, default 1.2
  b?: number; // length normalization, default 0.75
  tokenizer?: (text: string) => string[]; // default: unicodeTokenize
}): BM25Index;
```

`unicodeTokenize` splits on Unicode word boundaries, lowercases, and filters tokens with length > 1. It replaces the ASCII-only `extractKeywords` in `relevance.ts`.

**Updated `computeRelevance` signature:**

```ts
function computeRelevance(
  query: QueryContext,
  item: ContextItem,
  options?: { scoringMethod?: "keyword" | "bm25"; index?: BM25Index }
): number;
```

When `scoringMethod` is `"bm25"` (the default) and an `index` is provided, BM25 scoring is used. When no index is provided, the function builds a single-document index on the fly (less efficient but works for one-off calls). When `scoringMethod` is `"keyword"`, the old keyword overlap logic is used for backward compatibility.

**Integration with `createQueryAwareScorer`:**

The scorer builds a BM25 index from all items once, then passes it to `computeRelevance` for each item. `extractKeywords` in `relevance.ts` is updated to use `unicodeTokenize` instead of the ASCII regex.

**Implementation notes:**

- BM25 is ~50 lines with no external dependencies
- IDF = `ln((N - df + 0.5) / (df + 0.5) + 1)` where N = document count, df = docs containing term
- TF component = `(tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))`
- Both languages get identical implementations

**Files changed:**

- New: `packages/ce-core/src/bm25.ts`, `python/context_engineering/bm25.py`
- Modified: `packages/ce-core/src/relevance.ts`, `python/context_engineering/relevance.py` (use `unicodeTokenize`, update `computeRelevance` signature)
- Modified: `packages/ce-core/src/score.ts`, `python/context_engineering/core.py` (scorer builds BM25 index)
- Modified: `packages/ce-core/src/index.ts`, `python/context_engineering/__init__.py` (export `unicodeTokenize`, `createBM25Index`, `BM25Index`)

**Tests:**

- Unit tests for BM25 index: add, score, scoreAll, empty index, single document, Unicode text
- Unit tests for `unicodeTokenize`: ASCII, Unicode, CJK, emoji, empty string
- Integration tests: `createQueryAwareScorer` with BM25 produces better ordering than keyword overlap for known test cases
- Regression: existing relevance tests still pass (keyword mode)

---

### 1B. Input Validation for Extended Features

**Problem:** `pack()` validates inputs via Zod/Pydantic, giving structured errors. All extended features (`packWithAllocation`, `packWithCacheTopology`, `createSession`, `placeItems`, `createContextManager`, `pipeline.build()`) accept raw inputs with no validation. Invalid inputs produce confusing runtime errors.

**Solution:** Add Zod schemas for each extended feature's options. Validate at each public entry point.

**New schemas in `schemas.ts`:**

```ts
const KindAllocationSchema = z.object({
  kind: z.string().min(1),
  targetRatio: z.number().min(0).max(1),
  minTokens: z.number().int().nonnegative().optional(),
  maxTokens: z.number().int().positive().optional(),
  priority: z.number().int().nonnegative().optional(),
});

const CacheConfigSchema = z.object({
  provider: z.enum(["anthropic", "openai", "auto"]).optional(),
  minPrefixTokens: z.number().int().nonnegative().optional(),
  markBreakpoints: z.boolean().optional(),
});

const SessionOptionsSchema = z.object({
  budget: BudgetSchema,
  packOptions: z.object({}).passthrough().optional(),
});

const CompactionOptionsSchema = z.object({
  budget: BudgetSchema,
  summarizeAfterTurns: z.number().int().positive().optional(),
  preserveRecentTurns: z.number().int().nonnegative().optional(),
  systemPrompt: z.string().optional(),
});
// Note: 2A will extend this with batchSize and summarizer fields

const PlacementOptionsSchema = z.object({
  model: z.string().optional(),
  profile: z.array(z.number().finite()).optional(),
  strategy: z.enum(["score-order", "attention-optimized"]).optional(),
});
```

**Behavior:**

- Each extended function calls its validator at the top, before any logic
- Throws the same `ValidationError` with structured `details[].path` and `details[].message` that `pack()` uses
- Python gets equivalent Pydantic validation at each entry point
- Only public entry points validate — internal helpers called from validated contexts do not re-validate
- Pipeline `build()`/`buildAsync()` validates accumulated configuration before executing stages (delegates to the individual function validators)

**Files changed:**

- Modified: `packages/ce-core/src/schemas.ts` (new schemas)
- Modified: `allocation.ts`, `cache-topology.ts`, `session.ts`, `placement.ts`, `compaction.ts` (add validation calls)
- Modified: `packages/ce-core/src/pipeline.ts`, `python/context_engineering/pipeline.py` (validate in build/buildAsync)
- Modified: Python equivalents of all the above
- Modified: `packages/ce-core/src/index.ts` (export new schemas)

**Tests:**

- Each new schema: valid input passes, each invalid field produces correct error path/message
- Each extended function: invalid input throws ValidationError with structured details
- Pipeline: invalid allocation config throws before packing starts
- Existing tests continue to pass (they use valid inputs)

---

### 1C. Keyword-Based Redundancy Fallback

**Problem:** `eliminateRedundancy()` requires an `EmbeddingProvider` — network calls and API keys are mandatory. Many use cases (local dev, CI, cost-sensitive) need a good-enough heuristic.

**Solution:** Add a Jaccard similarity fallback when no `EmbeddingProvider` is supplied.

**Updated TS interface (breaking changes noted):**

```ts
interface RedundancyOptions {
  threshold?: number; // default: 0.85 (embedding), 0.8 (Jaccard) — see below
  strategy?: "recent" | "highest-priority"; // BREAKING: "summarize" removed (was unimplemented)
  embeddingProvider?: EmbeddingProvider; // BREAKING: renamed from "provider", now optional
  tokenizer?: (text: string) => string[]; // reuse unicodeTokenize from 1A
}
```

**Breaking change details:**

- `provider` → `embeddingProvider`: clearer name, now optional
- `similarityThreshold` → `threshold`: shorter name
- `"summarize"` strategy removed: it did the same thing as `"recent"`, never actually summarized
- `"highest-priority"` strategy added: pick the cluster member with highest priority; break ties by recency

**Default thresholds:** The threshold defaults are mode-dependent:

- Embedding mode (embeddingProvider set): `0.85` — cosine similarity on embeddings is more precise, lower threshold catches more near-duplicates
- Jaccard mode (no embeddingProvider): `0.8` — word overlap is noisier, higher threshold avoids false positives
- Explicit `threshold` value overrides both defaults

**Updated Python interface:**

```python
@dataclass
class RedundancyConfig:
    threshold: float = 0.8           # renamed from similarity_threshold
    strategy: str = "recent"         # "recent" | "highest-priority"
    embedding_provider: Optional[EmbeddingProvider] = None  # renamed from provider, now optional
    tokenizer: Optional[Callable[[str], List[str]]] = None
```

The Python `RedundancyEliminator` class is kept but updated to support the no-provider path. A standalone `eliminate_redundancy()` function is also added for API parity with TS:

```python
async def eliminate_redundancy(
    items: List[ContextItem],
    config: RedundancyConfig
) -> List[ContextItem]:
```

When `config.embedding_provider` is `None`, this function runs synchronously internally (Jaccard needs no async) but maintains the async signature for interface consistency. An explicit sync variant `eliminate_redundancy_sync()` is also provided.

**Algorithm (no embedding provider):**

1. Tokenize each item's content into a word set using `unicodeTokenize` from 1A (or custom `tokenizer`)
2. Leader-clustering: compare each item to cluster representatives via Jaccard similarity
3. Same threshold and strategy for picking the surviving item

**Integration:**

- `PackOptions` already has `redundancyConfig` — it's wired into `packAsync()`. Now also wire it into sync `pack()` for the Jaccard-only path.
- A new sync function `eliminateRedundancySync(items, options)` is created in `redundancy.ts` for the Jaccard-only code path. The existing async `eliminateRedundancy` is kept for the embedding path. `pack()` calls the sync variant when `redundancyConfig` has no `embeddingProvider`.
- `pipeline.build()` (sync) can now use redundancy elimination without `buildAsync()`

**EmbeddingProvider adapter (from prerequisite):**

- New: `packages/ce-providers/src/embedding-adapter.ts` — adapts ce-providers `EmbeddingProvider` to ce-core interface
- Exported from ce-providers index

**Files changed:**

- Modified: `packages/ce-core/src/redundancy.ts`, `python/context_engineering/redundancy.py`
- Modified: `packages/ce-core/src/pack.ts`, `python/context_engineering/core.py` (sync redundancy path)
- Modified: `packages/ce-core/src/types.ts` (update `RedundancyOptions` interface)
- Modified: `packages/ce-core/src/pipeline.ts`, `python/context_engineering/pipeline.py`
- New: `packages/ce-providers/src/embedding-adapter.ts`
- Modified: `packages/ce-providers/src/index.ts` (export adapter)

**Tests:**

- Keyword redundancy: items with >80% word overlap are clustered
- Strategy "recent": most recent item survives
- Strategy "highest-priority": highest priority item survives (ties broken by recency)
- Mode-dependent defaults: embedding mode uses 0.85, Jaccard mode uses 0.8
- Mixed mode: items with embeddings use cosine, items without use Jaccard
- Sync `pack()` with `redundancyConfig` works without embedding provider
- EmbeddingProvider adapter: ce-providers provider produces correct `number[][]` output
- Regression: existing async redundancy tests still pass

---

## Phase 2: "Better Compression"

### 2A. LLM Summarization in Compaction

**Problem:** `compaction.ts`/`compaction.py` `compile()` accepts a `Summarizer` option but never calls it. Compaction just truncates text, losing information from the end of older turns.

**Solution:** Wire the `Summarizer` into the compaction flow with batch-based summarization and graceful fallback.

**Async boundary design (resolves sync/async mismatch):**

The existing `Summarizer` type is synchronous: `(item: ContextItem, targetTokens: number) => ContextItem | null`. LLM calls are inherently async. Rather than make the sync `compile()` async (which would break the ContextManager interface for all users), we add a parallel async path:

```ts
// BREAKING: Summarizer becomes async
type Summarizer = (
  item: ContextItem,
  targetTokens: number
) => Promise<ContextItem | null>;

// ContextManager gains compileAsync()
interface ContextManager {
  compile(): CompileResult; // sync — truncation only (unchanged behavior)
  compileAsync(): Promise<CompileResult>; // NEW — supports LLM summarization
  // ... existing methods unchanged
}
```

- `compile()` (sync): Unchanged behavior. If a `summarizer` is provided, it is ignored in the sync path. Truncation only. This means existing callers are not affected.
- `compileAsync()` (new): Calls the `summarizer` for batch-based summarization. Falls back to truncation if no summarizer or on failure.
- The `Summarizer` type signature changes to return `Promise<...>` — this is a breaking change for any custom summarizer implementations, but since the existing summarizer was never called, no real-world code is affected.

**New `compileAsync()` flow:**

1. Separate turns into `olderTurns` and `recentTurns` (by `preserveRecent`) — unchanged
2. If `summarizer` is provided and older turns exceed budget:
   - Group older turns into batches (configurable `batchSize`, default 5 turns)
   - For each batch, create a synthetic `ContextItem` with concatenated batch content
   - Call `await summarizer(batchItem, perBatchTokenBudget)` — returns condensed `ContextItem` or `null`
   - If `null` or result exceeds per-batch token budget, fall back to truncation for that batch
3. If no `summarizer`, use truncation behavior (same as sync `compile()`)
4. Pack turns + items into final output — unchanged

**New CompactionOptions fields:**

```ts
interface CompactionOptions {
  // ... existing fields
  summarizer?: Summarizer; // BREAKING: now async signature
  batchSize?: number; // turns per summarization batch, default 5
}
```

**New in ce-providers — `createLLMSummarizer`:**

```ts
// packages/ce-providers/src/summarizer.ts
function createLLMSummarizer(options: {
  provider: LLMProvider;
  model?: string;
  maxOutputTokens?: number; // default 256
  prompt?: string; // custom system prompt
}): Summarizer;
```

Default prompt: "Summarize the following conversation turns into a concise paragraph that preserves key facts, decisions, and action items. Omit pleasantries and filler."

Returns a function matching the async `Summarizer` signature. Calls `provider.generate()`, returns new `ContextItem` with summarized content and re-estimated tokens.

**Python parity:** Same `create_llm_summarizer` factory added to `providers.py` (this file exists). Python `ContextManager.__init__` gains an optional `summarizer` parameter, and `create_context_manager()` gains the same kwarg. Python `ContextManager` gains `compile_async()` using `asyncio` coroutines.

**Error handling:** LLM call failure → summarizer returns `null` → compaction falls back to truncation for that batch. No crash, no data loss.

**Files changed:**

- Modified: `packages/ce-core/src/compaction.ts`, `python/context_engineering/compaction.py` (new `compileAsync`/`compile_async`, batch logic, Python gains `summarizer` param)
- Modified: `packages/ce-core/src/types.ts` (Summarizer type becomes async)
- Modified: `packages/ce-core/src/compaction.ts` (`CompactionOptions` gains `batchSize` field — this interface lives in compaction.ts, not types.ts)
- New: `packages/ce-providers/src/summarizer.ts`
- Modified: `python/context_engineering/providers.py` (add `create_llm_summarizer`)
- Modified: `packages/ce-providers/src/index.ts` (export factory)

**Tests:**

- `compileAsync`: summarizer called for older turns when provided
- Batching: 10 turns with batchSize=5 produces 2 summarizer calls
- Fallback: summarizer returning null → truncation for that batch
- Fallback: summarizer result exceeding budget → truncation for that batch
- Sync `compile()` ignores summarizer (unchanged behavior)
- No summarizer → identical behavior to today (truncation) in both sync and async
- Integration: `createLLMSummarizer` with mock provider produces valid output

---

### 2B. Pipeline Async Parity

**Problem:** `buildAsync()` ignores configured allocation, cache topology, and template stages. Users must choose between embedding support and full pipeline features.

**Solution:** Implement async variants of allocation and cache topology packing; call template directly.

**New async functions:**

```ts
async function packWithAllocationAsync(
  items: ContextItem[],
  budget: Budget,
  allocations: AllocationConfig[],
  options?: PackOptions
): Promise<AllocationResult>;

async function packWithCacheTopologyAsync(
  items: ContextItem[],
  budget: Budget,
  cacheConfig: CacheConfig,
  options?: PackOptions
): Promise<CacheAwarePack>;
```

These mirror their sync counterparts but delegate to `packAsync()` internally, supporting `embeddingProvider` and `redundancyConfig`.

**Updated `buildAsync()` stage sequence (TS):**

1. Determine items and options
2. **Pack:** allocation → `packWithAllocationAsync()`, cache topology → `packWithCacheTopologyAsync()`, else → `packAsync()`
3. **Placement:** `placeItems()` if configured
4. **Quality gate:** shared `applyQualityGate()` helper (extracted from duplicated code)
5. **Template:** `toMessages()` if configured
6. **Session:** track delta if configured
7. Return full `PipelineResult` with all fields (`cacheKey`, `allocations`, `messages`, etc.)

**Python: create `build_async()` from scratch.**

The Python `ContextPipeline` currently has only `build()`. A new `build_async()` method is created following the same stage sequence above, using `asyncio` coroutines. It calls `pack_async()`, `pack_with_allocation_async()`, or `pack_with_cache_topology_async()` (new async variants added to the respective Python modules).

**Shared extraction:** Quality gate loop extracted to private helper `_apply_quality_gate(selected, quality_fn, min_overall)`, used by both `build()` and `buildAsync()` / `build_async()`. Remove the `console.warn` calls added during the audit.

**Files changed:**

- Modified: `packages/ce-core/src/allocation.ts`, `python/context_engineering/allocation.py` (new async function)
- Modified: `packages/ce-core/src/cache-topology.ts`, `python/context_engineering/cache_topology.py` (new async function)
- Modified: `packages/ce-core/src/pipeline.ts` (buildAsync rewrite, quality gate extraction)
- Modified: `python/context_engineering/pipeline.py` (new `build_async()`, quality gate extraction)
- Modified: `packages/ce-core/src/index.ts`, `python/context_engineering/__init__.py` (export async variants)

**Tests:**

- `buildAsync()` with allocation produces same structure as `build()` with allocation
- `buildAsync()` with cache topology populates `cacheKey`, `cacheEfficiency`, `cacheableTokens`
- `buildAsync()` with template populates `messages` in result
- `buildAsync()` with embedding provider + allocation eliminates redundancy within each kind
- Python `build_async()`: same test matrix as TS `buildAsync()`
- Quality gate helper produces identical results when called from both paths
- Regression: existing `build()` and `buildAsync()` tests still pass

---

## Phase 3: "Better Durability"

### 3A. FileStore Advisory File Locking

**Problem:** `FileStore` uses atomic writes (tmp + rename) but has no cross-process protection. Two processes on the same JSONL file can overwrite each other's data.

**Solution:** Advisory file locking using OS-level exclusive file creation.

**TS implementation — new internal helper:**

```ts
async function withFileLock<T>(
  lockPath: string,
  fn: () => Promise<T>,
  options?: { timeout?: number; retryInterval?: number; staleLockAge?: number }
): Promise<T>;
```

- Acquires via `fs.open(lockPath, 'wx')` (exclusive create)
- On failure, retries with exponential backoff up to `timeout` (default 5000ms)
- Stale lock detection: if lock file is older than `staleLockAge` (default 30000ms), steal it
- Lock file contains PID + timestamp for diagnostics
- `persistWithMutation` wraps its write inside `withFileLock`

**Python implementation:**

- Same pattern using `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`
- The existing `threading.Lock` handles in-process concurrency; file lock handles cross-process

**New FileStore options:**

```ts
interface FileStoreOptions {
  path: string;
  lockTimeout?: number; // ms, default 5000
  staleLockAge?: number; // ms, default 30000
  disableLocking?: boolean; // opt-out, default false
}
```

**Documented limitation:** File locking prevents concurrent writes but does not prevent read-modify-write conflicts. JSONL is a single-writer format. The lock prevents corruption, not conflict resolution.

**Files changed:**

- Modified: `packages/ce-memory/src/file-store.ts`, `python/context_engineering/memory.py`
- Modified: `packages/ce-memory/src/index.ts` (export updated options type)

**Tests:**

- Lock acquisition and release around writes
- Stale lock detection: old lock file is stolen
- Timeout: lock acquisition fails after timeout with clear error
- `disableLocking: true` skips locking entirely
- Concurrent writes from same process still serialized via internal queue/lock (regression guard)
- Lock file is cleaned up after write, even on error (finally block)

---

### 3B. Python ContextSession Thread Safety

**Problem:** `ContextSession` reads and writes `_previous_manifest`, `_compile_count`, and `_current_items` without synchronization. Concurrent `compile()` calls from multiple threads can corrupt state.

**Solution:** Add `threading.Lock` around all state-mutating operations.

**Changes to `session.py`:**

```python
class ContextSession:
    def __init__(self, budget, **options):
        self._lock = threading.Lock()
        # ... existing init

    def add_items(self, items):
        with self._lock:
            # existing logic

    def remove_items(self, ids):
        with self._lock:
            # existing logic

    def compile(self):
        with self._lock:
            # existing logic

    def clear(self):
        with self._lock:
            # existing logic

    def item_count(self):
        with self._lock:
            return len(self._current_items)

    def get_compile_count(self):
        with self._lock:
            return self._compile_count
```

**TS counterpart:** Not needed — JavaScript is single-threaded per isolate.

**Files changed:**

- Modified: `python/context_engineering/session.py`

**Tests:**

- Existing session tests pass unchanged (single-threaded usage)
- New test: concurrent `compile()` calls from multiple threads produce consistent state (no duplicate items, no lost updates)

---

## Phase Sequencing

```
Phase 1 (Better Selection)     Phase 3 (Better Durability)
  1A. BM25 relevance             3A. FileStore locking
  1B. Input validation           3B. Session thread safety
  1C. Redundancy fallback            |
        |                            | (can run in parallel)
        v                            v
Phase 2 (Better Compression)
  2A. LLM summarization
  2B. Pipeline async parity
```

Phase 3 has no dependency on Phases 1 or 2 and can be done in parallel. Phase 2 depends on Phase 1C (redundancy in sync pack) for the pipeline async work to have the full feature set available.

Within Phase 1, the order matters: 1A ships the tokenizer that 1C depends on. 1B can be done in parallel with 1A or 1C.

---

## Out of Scope

- API surface cleanup (leaky exports, naming parity) — separate effort
- Test coverage gaps (segmentation, framework, eval) — separate effort
- Web client/server improvements — separate effort
- Schema-driven types (Zod → z.infer) — separate effort
- Attention profile interpolation — future optimization
