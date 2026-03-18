# Context Engineering Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the Context Engineering Toolkit with better relevance scoring (BM25), input validation, keyword-based redundancy fallback, LLM summarization in compaction, full async pipeline parity, and concurrency safety.

**Architecture:** Three phases — Phase 1 (selection quality), Phase 2 (compression + async), Phase 3 (durability). Phase 3 can run in parallel with 1 & 2. Phase 2 depends on Phase 1C.

**Tech Stack:** TypeScript (Vitest), Python 3.10+ (pytest), Zod (TS validation), Pydantic (Python validation). No new external dependencies.

**Spec:** `docs/superpowers/specs/2026-03-18-context-engineering-improvements-design.md`

---

## File Structure

### New files

- `packages/ce-core/src/bm25.ts` — BM25 index + Unicode tokenizer
- `packages/ce-core/src/bm25.test.ts` — BM25 unit tests
- `python/context_engineering/bm25.py` — Python BM25 index + tokenizer
- `python/tests/test_bm25.py` — Python BM25 tests
- `packages/ce-providers/src/embedding-adapter.ts` — Adapts ce-providers EmbeddingProvider to ce-core interface
- `packages/ce-providers/src/summarizer.ts` — LLM summarizer factory

### Modified files (by phase)

**Phase 1A:** `relevance.ts`, `relevance.py`, `score.ts`, `core.py`, `index.ts`, `__init__.py`
**Phase 1B:** `schemas.ts`, `allocation.ts`, `cache-topology.ts`, `session.ts`, `placement.ts`, `compaction.ts`, `pipeline.ts` + Python equivalents
**Phase 1C:** `redundancy.ts`, `redundancy.py`, `pack.ts`, `core.py`, `types.ts`, `pipeline.ts`, `pipeline.py`, `index.ts`, `__init__.py`
**Phase 2A:** `compaction.ts`, `compaction.py`, `types.ts`, `providers.py`, `ce-providers/index.ts`
**Phase 2B:** `allocation.ts`, `allocation.py`, `cache-topology.ts`, `cache_topology.py`, `pipeline.ts`, `pipeline.py`, `index.ts`, `__init__.py`
**Phase 3A:** `file-store.ts`, `memory.py`
**Phase 3B:** `session.py`

---

## Phase 1: Better Selection

### Task 1: BM25 Unicode Tokenizer (TS)

**Files:**

- Create: `packages/ce-core/src/bm25.ts`
- Create: `packages/ce-core/src/bm25.test.ts`

- [ ] **Step 1: Write failing tests for `unicodeTokenize`**

In `packages/ce-core/src/bm25.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { unicodeTokenize } from "./bm25.js";

describe("unicodeTokenize", () => {
  it("tokenizes ASCII text into lowercase words", () => {
    expect(unicodeTokenize("Hello World")).toEqual(["hello", "world"]);
  });

  it("filters tokens with length <= 1", () => {
    expect(unicodeTokenize("I am a dog")).toEqual(["am", "dog"]);
  });

  it("handles Unicode characters", () => {
    const tokens = unicodeTokenize("café résumé naïve");
    expect(tokens).toContain("café");
    expect(tokens).toContain("résumé");
    expect(tokens).toContain("naïve");
  });

  it("handles CJK by splitting on boundaries", () => {
    const tokens = unicodeTokenize("hello 世界");
    expect(tokens).toContain("hello");
    expect(tokens.length).toBeGreaterThanOrEqual(1);
  });

  it("returns empty array for empty string", () => {
    expect(unicodeTokenize("")).toEqual([]);
  });

  it("handles mixed alphanumeric", () => {
    const tokens = unicodeTokenize("node16 react19 ts5");
    expect(tokens).toContain("node16");
    expect(tokens).toContain("react19");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/ce-core && npx vitest run src/bm25.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `unicodeTokenize`**

In `packages/ce-core/src/bm25.ts`:

```ts
/**
 * Unicode-aware tokenizer. Splits on word boundaries, lowercases,
 * filters tokens with length <= 1.
 */
export function unicodeTokenize(text: string): string[] {
  if (!text) return [];
  const matches = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  return matches.filter(w => w.length > 1);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/ce-core && npx vitest run src/bm25.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ce-core/src/bm25.ts packages/ce-core/src/bm25.test.ts
git commit -m "feat(ce-core): add Unicode tokenizer for BM25"
```

---

### Task 2: BM25 Index (TS)

**Files:**

- Modify: `packages/ce-core/src/bm25.ts`
- Modify: `packages/ce-core/src/bm25.test.ts`

- [ ] **Step 1: Write failing tests for BM25 index**

Append to `packages/ce-core/src/bm25.test.ts`:

```ts
import { createBM25Index } from "./bm25.js";

describe("createBM25Index", () => {
  it("scores a matching document higher than non-matching", () => {
    const idx = createBM25Index();
    idx.add("doc1", "context engineering for language models");
    idx.add("doc2", "cooking recipes for pasta dishes");
    const s1 = idx.score("context engineering", "doc1");
    const s2 = idx.score("context engineering", "doc2");
    expect(s1).toBeGreaterThan(s2);
    expect(s2).toBe(0);
  });

  it("scoreAll returns scores for all documents", () => {
    const idx = createBM25Index();
    idx.add("a", "token budget packing");
    idx.add("b", "token estimation heuristic");
    idx.add("c", "unrelated content about weather");
    const scores = idx.scoreAll("token budget");
    expect(scores.get("a")).toBeGreaterThan(0);
    expect(scores.get("b")).toBeGreaterThan(0);
    expect(scores.get("c")).toBe(0);
    expect(scores.get("a")!).toBeGreaterThan(scores.get("b")!);
  });

  it("returns 0 for empty index", () => {
    const idx = createBM25Index();
    expect(idx.score("anything", "nonexistent")).toBe(0);
  });

  it("returns 0 for empty query", () => {
    const idx = createBM25Index();
    idx.add("doc1", "some content");
    expect(idx.score("", "doc1")).toBe(0);
  });

  it("tracks documentCount", () => {
    const idx = createBM25Index();
    expect(idx.documentCount).toBe(0);
    idx.add("a", "one");
    idx.add("b", "two");
    expect(idx.documentCount).toBe(2);
  });

  it("accepts custom k1 and b parameters", () => {
    const idx = createBM25Index({ k1: 2.0, b: 0.5 });
    idx.add("doc1", "test test test");
    const score = idx.score("test", "doc1");
    expect(score).toBeGreaterThan(0);
  });

  it("accepts custom tokenizer", () => {
    const idx = createBM25Index({
      tokenizer: text => text.split(",").map(s => s.trim().toLowerCase()),
    });
    idx.add("doc1", "alpha, beta, gamma");
    expect(idx.score("alpha", "doc1")).toBeGreaterThan(0);
  });

  it("IDF: rare terms score higher than common terms", () => {
    const idx = createBM25Index();
    idx.add("d1", "the common word appears here");
    idx.add("d2", "the common word too");
    idx.add("d3", "rare unique specialized term");
    // "rare" appears in 1 doc, "common" in 2 — IDF of rare > IDF of common
    const rareScore = idx.score("rare", "d3");
    const commonScore = idx.score("common", "d1");
    expect(rareScore).toBeGreaterThan(commonScore);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/ce-core && npx vitest run src/bm25.test.ts`
Expected: FAIL — `createBM25Index` not exported

- [ ] **Step 3: Implement BM25 index**

Append to `packages/ce-core/src/bm25.ts`:

```ts
export interface BM25Index {
  add(id: string, text: string): void;
  score(query: string, id: string): number;
  scoreAll(query: string): Map<string, number>;
  readonly documentCount: number;
}

export function createBM25Index(options?: {
  k1?: number;
  b?: number;
  tokenizer?: (text: string) => string[];
}): BM25Index {
  const k1 = options?.k1 ?? 1.2;
  const b = options?.b ?? 0.75;
  const tokenize = options?.tokenizer ?? unicodeTokenize;

  // Document store: id -> token frequencies
  const docs = new Map<string, Map<string, number>>();
  // Document lengths in tokens
  const docLengths = new Map<string, number>();
  // Document frequency: term -> count of docs containing it
  const df = new Map<string, number>();
  let totalLength = 0;

  function add(id: string, text: string): void {
    const tokens = tokenize(text);
    const freq = new Map<string, number>();
    for (const t of tokens) {
      freq.set(t, (freq.get(t) ?? 0) + 1);
    }
    docs.set(id, freq);
    docLengths.set(id, tokens.length);
    totalLength += tokens.length;

    // Update document frequency
    for (const term of freq.keys()) {
      df.set(term, (df.get(term) ?? 0) + 1);
    }
  }

  function score(query: string, id: string): number {
    const docFreq = docs.get(id);
    if (!docFreq) return 0;
    const queryTokens = tokenize(query);
    if (queryTokens.length === 0) return 0;

    const N = docs.size;
    const dl = docLengths.get(id) ?? 0;
    const avgdl = N > 0 ? totalLength / N : 1;
    let total = 0;

    for (const term of queryTokens) {
      const termDf = df.get(term) ?? 0;
      const tf = docFreq.get(term) ?? 0;
      if (tf === 0) continue;

      const idf = Math.log((N - termDf + 0.5) / (termDf + 0.5) + 1);
      const tfNorm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + (b * dl) / avgdl));
      total += idf * tfNorm;
    }

    return total;
  }

  function scoreAll(query: string): Map<string, number> {
    const result = new Map<string, number>();
    for (const id of docs.keys()) {
      result.set(id, score(query, id));
    }
    return result;
  }

  return {
    add,
    score,
    scoreAll,
    get documentCount() {
      return docs.size;
    },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/ce-core && npx vitest run src/bm25.test.ts`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ce-core/src/bm25.ts packages/ce-core/src/bm25.test.ts
git commit -m "feat(ce-core): add BM25 index implementation"
```

---

### Task 3: BM25 Index (Python)

**Files:**

- Create: `python/context_engineering/bm25.py`
- Create: `python/tests/test_bm25.py`

- [ ] **Step 1: Write failing tests**

Create `python/tests/test_bm25.py` with equivalent tests to the TS version: `unicode_tokenize` (ASCII, Unicode, CJK, empty) and `create_bm25_index` (scoring, scoreAll, IDF, empty, custom params). Mirror the TS test cases.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd python && python -m pytest tests/test_bm25.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement Python BM25**

Create `python/context_engineering/bm25.py` with `unicode_tokenize(text)` using `re.findall(r'[\w]+', text.lower(), re.UNICODE)` and `create_bm25_index(k1, b, tokenizer)` returning a `BM25Index` object. Same algorithm as TS.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd python && python -m pytest tests/test_bm25.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add python/context_engineering/bm25.py python/tests/test_bm25.py
git commit -m "feat(python): add BM25 index implementation"
```

---

### Task 4: Integrate BM25 into Relevance Scoring (TS)

**Files:**

- Modify: `packages/ce-core/src/relevance.ts`
- Modify: `packages/ce-core/src/score.ts`
- Modify: `packages/ce-core/src/relevance.test.ts`
- Modify: `packages/ce-core/src/index.ts`

- [ ] **Step 1: Write failing test for BM25-based `computeRelevance`**

Add to `packages/ce-core/src/relevance.test.ts`:

```ts
it("uses BM25 scoring when scoringMethod is bm25", async () => {
  const { createBM25Index } = await import("./bm25.js");
  const idx = createBM25Index();
  idx.add("item1", "context engineering token budget");
  idx.add("item2", "cooking pasta recipes");

  const query: QueryContext = { text: "context engineering" };
  const item1: ContextItem = {
    id: "item1",
    content: "context engineering token budget",
  };
  const item2: ContextItem = { id: "item2", content: "cooking pasta recipes" };

  const score1 = computeRelevance(query, item1, {
    scoringMethod: "bm25",
    index: idx,
  });
  const score2 = computeRelevance(query, item2, {
    scoringMethod: "bm25",
    index: idx,
  });
  expect(score1).toBeGreaterThan(score2);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/ce-core && npx vitest run src/relevance.test.ts`
Expected: FAIL — `computeRelevance` does not accept options parameter

- [ ] **Step 3: Update `computeRelevance` to accept options and use BM25**

In `packages/ce-core/src/relevance.ts`:

1. Import `{ createBM25Index, type BM25Index }` from `./bm25.js`
2. Add options parameter to `computeRelevance`:
   ```ts
   export function computeRelevance(
     query: QueryContext,
     item: ContextItem,
     options?: { scoringMethod?: "keyword" | "bm25"; index?: BM25Index }
   ): number {
     if (query.embedding && item.embedding) {
       return embeddingRelevance(query.embedding, item.embedding);
     }
     // Explicit keyword mode
     if (options?.scoringMethod === "keyword") {
       return keywordRelevance(query, item);
     }
     // Default: BM25 (BREAKING: was keyword)
     if (options?.index) {
       const rawScore = options.index.score(query.text, item.id);
       return rawScore / (rawScore + 1);
     }
     // No index provided — build single-doc index on the fly (less efficient)
     const idx = createBM25Index();
     idx.add(item.id, item.content);
     const rawScore = idx.score(query.text, item.id);
     return rawScore / (rawScore + 1);
   }
   ```
3. Update `extractKeywords` to use `unicodeTokenize`:
   ```ts
   import { unicodeTokenize } from "./bm25.js";
   export function extractKeywords(text: string): Set<string> {
     const words = unicodeTokenize(text);
     return new Set(words.filter(w => !STOPWORDS.has(w)));
   }
   ```

- [ ] **Step 4: Update `createQueryAwareScorer` in `score.ts` to build BM25 index**

The scorer should accept items to build the index, then use it. This requires updating `createQueryAwareScorer` to accept an `items` parameter for pre-building the index. Add the items parameter and use BM25:

```ts
export function createQueryAwareScorer(
  query: QueryInput,
  weights: ScoringWeights = {},
  items?: ContextItem[]
): ItemScorer {
  const w = { ...DEFAULT_WEIGHTS, relevance: 0.8, ...weights };
  const queryCtx = normalizeQuery(query);

  // Build BM25 index if items provided
  let bm25Index: BM25Index | undefined;
  if (items) {
    bm25Index = createBM25Index();
    for (const item of items) {
      bm25Index.add(item.id, item.content);
    }
  }

  return (item: ContextItem) => {
    if (typeof item.score === "number") return item.score;
    const priority = item.priority ?? 0;
    const recency = item.recency ?? 0;
    const salience =
      typeof item.metadata?.salience === "number" ? item.metadata.salience : 0;
    const relevance = computeRelevance(queryCtx, item, {
      scoringMethod: bm25Index ? "bm25" : "keyword",
      index: bm25Index,
    });
    return (
      priority * w.priority +
      recency * w.recency +
      salience * w.salience +
      relevance * (w.relevance ?? 0)
    );
  };
}
```

- [ ] **Step 5: Update `pack.ts` to pass items to query-aware scorer**

In `packages/ce-core/src/pack.ts`, where `createQueryAwareScorer` is called (when `options.query` is set), pass the items array so the scorer can build a BM25 index:

```ts
// Before:
const scorer = options.query ? createQueryAwareScorer(options.query, options.weights) : ...
// After:
const scorer = options.query ? createQueryAwareScorer(options.query, options.weights, items) : ...
```

- [ ] **Step 6: Export BM25 from index.ts**

Add to `packages/ce-core/src/index.ts`:

```ts
export * from "./bm25.js";
```

- [ ] **Step 6: Run all relevance and score tests**

Run: `cd packages/ce-core && npx vitest run src/relevance.test.ts src/score.test.ts src/bm25.test.ts`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add packages/ce-core/src/relevance.ts packages/ce-core/src/score.ts packages/ce-core/src/relevance.test.ts packages/ce-core/src/index.ts
git commit -m "feat(ce-core): integrate BM25 into relevance scoring and query-aware scorer"
```

---

### Task 5: Integrate BM25 into Python Relevance Scoring

**Files:**

- Modify: `python/context_engineering/relevance.py`
- Modify: `python/context_engineering/core.py`
- Modify: `python/context_engineering/__init__.py`
- Modify: `python/tests/test_relevance.py`

Mirror Task 4 for Python: update `compute_relevance` to accept `scoring_method` and `index` options, update `extract_keywords` to use `unicode_tokenize`, update `create_query_aware_scorer` in `core.py` to build BM25 index when items are available. Export `unicode_tokenize`, `create_bm25_index`, `BM25Index` from `__init__.py`.

- [ ] **Step 1-4: TDD cycle** — write failing test, implement, verify pass
- [ ] **Step 5: Commit**

```bash
git add python/context_engineering/relevance.py python/context_engineering/core.py python/context_engineering/__init__.py python/tests/test_relevance.py
git commit -m "feat(python): integrate BM25 into relevance scoring"
```

---

### Task 6: Input Validation Schemas (TS)

**Files:**

- Modify: `packages/ce-core/src/schemas.ts`
- Modify: `packages/ce-core/src/schemas.test.ts`
- Modify: `packages/ce-core/src/allocation.ts`
- Modify: `packages/ce-core/src/cache-topology.ts`
- Modify: `packages/ce-core/src/placement.ts`
- Modify: `packages/ce-core/src/compaction.ts`
- Modify: `packages/ce-core/src/session.ts`
- Modify: `packages/ce-core/src/pipeline.ts`

- [ ] **Step 1: Write failing tests for each new schema**

Add to `packages/ce-core/src/schemas.test.ts` — one `describe` block per schema (`KindAllocationSchema`, `CacheConfigSchema`, `CompactionOptionsSchema`, `PlacementOptionsSchema`, `SessionOptionsSchema`). Test valid input passes, each invalid field produces correct error.

- [ ] **Step 2: Implement schemas in `schemas.ts`**

Add schemas matching the actual interfaces (see spec for exact field definitions). Use `BudgetSchema` for budget fields.

- [ ] **Step 3: Add validation calls to each extended function**

At the top of each function (`packWithAllocation`, `packWithCacheTopology`, `placeItems`, `createContextManager`, `createSession`), add a `validateFoo(input)` call that throws `ValidationError` on bad input. Follow the `validatePackInputs` pattern already in `schemas.ts`.

- [ ] **Step 4: Run all tests**

Run: `cd packages/ce-core && npx vitest run`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ce-core/src/schemas.ts packages/ce-core/src/schemas.test.ts packages/ce-core/src/allocation.ts packages/ce-core/src/cache-topology.ts packages/ce-core/src/placement.ts packages/ce-core/src/compaction.ts packages/ce-core/src/session.ts packages/ce-core/src/pipeline.ts
git commit -m "feat(ce-core): add input validation for all extended features"
```

---

### Task 7: Input Validation (Python)

Mirror Task 6 for Python. Add Pydantic validation at each public entry point in the Python equivalents. Follow the existing Pydantic patterns.

- [ ] **Step 1-4: TDD cycle**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(python): add input validation for all extended features"
```

---

### Task 8: Keyword Redundancy Fallback + EmbeddingProvider Adapter (TS)

**Files:**

- Modify: `packages/ce-core/src/redundancy.ts`
- Modify: `packages/ce-core/src/redundancy.test.ts`
- Modify: `packages/ce-core/src/types.ts`
- Modify: `packages/ce-core/src/pack.ts`
- Create: `packages/ce-providers/src/embedding-adapter.ts`
- Modify: `packages/ce-providers/src/index.ts`

- [ ] **Step 1: Write failing tests for Jaccard redundancy**

Add to `packages/ce-core/src/redundancy.test.ts`:

```ts
describe("eliminateRedundancySync (Jaccard)", () => {
  it("clusters items with >80% word overlap", () => {
    const items = [
      createContextItem("a", "the quick brown fox jumps over the lazy dog"),
      createContextItem("b", "the quick brown fox jumps over the lazy cat"),
      createContextItem(
        "c",
        "completely unrelated content about space rockets"
      ),
    ];
    const result = eliminateRedundancySync(items, {
      threshold: 0.8,
      strategy: "recent",
    });
    expect(result.length).toBe(2); // a+b clustered, c separate
  });

  it("highest-priority strategy picks highest priority item", () => {
    const items = [
      { ...createContextItem("a", "same words repeated here"), priority: 1 },
      { ...createContextItem("b", "same words repeated here"), priority: 10 },
    ];
    const result = eliminateRedundancySync(items, {
      threshold: 0.8,
      strategy: "highest-priority",
    });
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("b");
  });

  it("uses 0.8 default threshold in Jaccard mode (no embeddingProvider)", () => {
    // Items with ~75% overlap should NOT be clustered at 0.8 threshold
    const items = [
      createContextItem("a", "alpha beta gamma delta epsilon"),
      createContextItem("b", "alpha beta gamma delta zeta"), // 4/6 = 0.67 Jaccard
    ];
    const result = eliminateRedundancySync(items, { strategy: "recent" });
    expect(result.length).toBe(2); // not clustered at 0.8
  });
});

describe("eliminateRedundancy (async, embedding mode)", () => {
  it("uses 0.85 default threshold when embeddingProvider is set", async () => {
    const mockProvider = {
      embed: async (texts: string[]) => texts.map(() => [1, 0, 0]),
    };
    const result = await eliminateRedundancy(
      [createContextItem("a", "x"), createContextItem("b", "y")],
      { embeddingProvider: mockProvider }
    );
    // All identical embeddings → similarity = 1.0 > 0.85 → clustered
    expect(result.length).toBe(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement**

1. Update `RedundancyOptions` in `redundancy.ts` (where it is defined, NOT types.ts): rename `provider` to `embeddingProvider` (optional), rename `similarityThreshold` to `threshold`, change strategy to `"recent" | "highest-priority"`. Add mode-dependent default threshold logic (0.85 for embedding, 0.8 for Jaccard).
2. Add `eliminateRedundancySync` to `redundancy.ts`: Jaccard similarity using `unicodeTokenize`, leader clustering, strategy resolution.
3. Update existing `eliminateRedundancy` to use the new interface names.
4. Wire sync redundancy into `pack.ts`: when `redundancyConfig` has no `embeddingProvider`, call `eliminateRedundancySync` before scoring.
5. Create `packages/ce-providers/src/embedding-adapter.ts` with `adaptEmbeddingProvider` function.
6. Export adapter from `packages/ce-providers/src/index.ts`.

- [ ] **Step 4: Run all tests**

Run: `cd packages/ce-core && npx vitest run`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ce-core/src/redundancy.ts packages/ce-core/src/redundancy.test.ts packages/ce-core/src/types.ts packages/ce-core/src/pack.ts packages/ce-providers/src/embedding-adapter.ts packages/ce-providers/src/index.ts
git commit -m "feat(ce-core): keyword-based redundancy fallback + embedding adapter"
```

---

### Task 9: Keyword Redundancy Fallback (Python)

Mirror Task 8 for Python. Update `RedundancyConfig` class (rename fields, add optional `embedding_provider`, add `tokenizer`). Add `eliminate_redundancy_sync()` function. Wire into sync `pack()`.

- [ ] **Step 1-4: TDD cycle**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(python): keyword-based redundancy fallback"
```

---

## Phase 2: Better Compression

### Task 10: Async Summarizer Type + `compileAsync` (TS)

**Files:**

- Modify: `packages/ce-core/src/types.ts`
- Modify: `packages/ce-core/src/compaction.ts`
- Modify: `packages/ce-core/src/compaction.test.ts`

- [ ] **Step 1: Write failing tests for `compileAsync` with mock summarizer**

Add to `packages/ce-core/src/compaction.test.ts`:

```ts
describe("compileAsync", () => {
  it("calls summarizer for older turns when provided", async () => {
    const calls: string[] = [];
    const mockSummarizer: Summarizer = async (item, targetTokens) => {
      calls.push(item.content);
      return { ...item, content: "summary", tokens: 5 };
    };
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      summarizer: mockSummarizer,
    });
    // Add enough turns to trigger summarization
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({
        role: "user",
        content: `turn content ${i} with enough words`,
      });
    }
    const result = await ctx.compileAsync();
    expect(calls.length).toBeGreaterThan(0);
    expect(result.totalTokens).toBeLessThan(200);
  });

  it("falls back to truncation when summarizer returns null", async () => {
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      summarizer: async () => null,
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    const result = await ctx.compileAsync();
    expect(result.turns.length).toBeGreaterThan(0);
  });

  it("batches older turns: 10 turns with batchSize=5 produces 2 summarizer calls", async () => {
    let callCount = 0;
    const mockSummarizer = async (item: any, target: number) => {
      callCount++;
      return { ...item, content: `summary ${callCount}`, tokens: 5 };
    };
    const ctx = createContextManager({
      budget: { maxTokens: 500 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: mockSummarizer,
      batchSize: 5,
    });
    for (let i = 0; i < 11; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i} content here` });
    }
    await ctx.compileAsync();
    expect(callCount).toBe(2); // 10 older turns / batchSize 5 = 2 batches
  });

  it("falls back to truncation when summarizer result exceeds budget", async () => {
    const ctx = createContextManager({
      budget: { maxTokens: 100 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: async (item, target) => {
        // Return a result that exceeds the per-batch budget
        return { ...item, content: "x".repeat(1000), tokens: 999 };
      },
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    const result = await ctx.compileAsync();
    // Should still produce output via truncation fallback
    expect(result.turns.length).toBeGreaterThan(0);
    expect(result.totalTokens).toBeLessThanOrEqual(100);
  });

  it("sync compile ignores summarizer", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      summarizer: async () => {
        throw new Error("should not be called");
      },
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    // sync compile should not call async summarizer
    expect(() => ctx.compile()).not.toThrow();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement**

1. In `types.ts`: Add new `AsyncSummarizer` type (keep existing sync `Summarizer` unchanged for `pack()` compression):
   ```ts
   export type AsyncSummarizer = (
     item: ContextItem,
     targetTokens: number
   ) => Promise<ContextItem | null>;
   ```
2. In `compaction.ts`: Add `batchSize` and `asyncSummarizer?: AsyncSummarizer` to `CompactionOptions`. Add `compileAsync` to `ContextManager` interface and implementation. The async compile groups older turns into batches, calls `asyncSummarizer` per batch, falls back to truncation on null/error. Sync `compile` is unchanged (uses truncation only). The existing sync `summarizer` field on `CompactionOptions` is left untouched for backward compat with `pack()` compression.

- [ ] **Step 4: Run all compaction tests**

Run: `cd packages/ce-core && npx vitest run src/compaction.test.ts`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ce-core/src/types.ts packages/ce-core/src/compaction.ts packages/ce-core/src/compaction.test.ts
git commit -m "feat(ce-core): async summarizer type + compileAsync with batch summarization"
```

---

### Task 11: LLM Summarizer Factory (TS)

**Files:**

- Create: `packages/ce-providers/src/summarizer.ts`
- Modify: `packages/ce-providers/src/index.ts`

- [ ] **Step 1: Write failing test**

Create test in `packages/ce-providers/src/providers.test.ts` (append):

```ts
describe("createLLMSummarizer", () => {
  it("returns summarized content from provider", async () => {
    const mockProvider = {
      generate: vi.fn().mockResolvedValue({
        content: "Concise summary of the conversation.",
        usage: { inputTokens: 100, outputTokens: 20, totalTokens: 120 },
      }),
    };
    const summarizer = createLLMSummarizer({ provider: mockProvider as any });
    const item = {
      id: "batch1",
      content: "Long conversation content...",
      tokens: 500,
    };
    const result = await summarizer(item, 50);
    expect(result).not.toBeNull();
    expect(result!.content).toBe("Concise summary of the conversation.");
    expect(mockProvider.generate).toHaveBeenCalled();
  });

  it("returns null on provider error", async () => {
    const mockProvider = {
      generate: vi.fn().mockRejectedValue(new Error("API error")),
    };
    const summarizer = createLLMSummarizer({ provider: mockProvider as any });
    const result = await summarizer({ id: "x", content: "text" }, 50);
    expect(result).toBeNull();
  });
});
```

- [ ] **Step 2-4: Implement, verify**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ce-providers): add createLLMSummarizer factory"
```

---

### Task 12: Async Summarizer + `compile_async` (Python)

Mirror Tasks 10-11 for Python. Update `Summarizer` type to async, add `compile_async` to `ContextManager`, add `create_llm_summarizer` to `providers.py`.

- [ ] **Step 1-4: TDD cycle**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(python): async summarizer + compile_async + LLM summarizer factory"
```

---

### Task 13: Async Allocation + Cache Topology (TS)

**Files:**

- Modify: `packages/ce-core/src/allocation.ts`
- Modify: `packages/ce-core/src/cache-topology.ts`
- Modify: `packages/ce-core/src/index.ts`

- [ ] **Step 1: Write failing tests for `packWithAllocationAsync` and `packWithCacheTopologyAsync`**

- [ ] **Step 2-3: Implement async variants that delegate to `packAsync` internally**

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ce-core): async variants for allocation and cache topology packing"
```

---

### Task 14: Pipeline `buildAsync` Full Parity (TS)

**Files:**

- Modify: `packages/ce-core/src/pipeline.ts`
- Modify: `packages/ce-core/src/pipeline.test.ts`

- [ ] **Step 1: Write failing tests** — `buildAsync` with allocation, cache topology, template, and combined

- [ ] **Step 2: Extract quality gate to shared helper `applyQualityGate`**

- [ ] **Step 3: Rewrite `buildAsync` to follow the full 7-stage sequence**

Remove the `console.warn` calls added during the audit. Add all missing stages.

- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(ce-core): full async pipeline parity with allocation, cache topology, template"
```

---

### Task 15: Pipeline Async Parity (Python)

Create `build_async` from scratch in Python pipeline. Add async variants to Python allocation and cache topology modules. Extract quality gate helper.

- [ ] **Step 1-4: TDD cycle**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(python): full async pipeline with build_async, allocation, cache topology"
```

---

## Phase 3: Better Durability (can run in parallel with Phase 1-2)

### Task 16: FileStore Advisory File Locking (TS)

**Files:**

- Modify: `packages/ce-memory/src/file-store.ts`
- Modify: `packages/ce-memory/src/memory.test.ts`

- [ ] **Step 1: Write failing tests**

Add to `packages/ce-memory/src/memory.test.ts`:

```ts
describe("FileStore locking", () => {
  it("creates and removes lock file around writes", async () => {
    const store = new FileStore(tmpPath, { lockTimeout: 1000 });
    await store.put({ content: "test" });
    // Lock file should not exist after write
    await expect(fs.access(tmpPath + ".lock")).rejects.toThrow();
    await store.close();
  });

  it("cleans up lock file on write error", async () => {
    // Force a write error by making the directory read-only after load
    // Verify lock file is cleaned up in finally block
  });

  it("disableLocking skips lock entirely", async () => {
    const store = new FileStore(tmpPath, { disableLocking: true });
    await store.put({ content: "test" });
    await store.close();
  });
});
```

- [ ] **Step 2-3: Implement `withFileLock` helper and integrate into `persistWithMutation`**

Add `withFileLock` as a private async function in `file-store.ts`. Uses `fs.open(lockPath, 'wx')` for exclusive create, exponential backoff retry, stale lock detection (check mtime > staleLockAge), PID+timestamp in lock file content.

Update `FileStoreOptions` with `lockTimeout`, `staleLockAge`, `disableLocking`.

Wrap `persistWithMutation`'s write sequence inside `withFileLock` (unless `disableLocking` is true).

- [ ] **Step 4: Run tests, verify pass**

Run: `cd packages/ce-memory && npx vitest run src/memory.test.ts`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add packages/ce-memory/src/file-store.ts packages/ce-memory/src/memory.test.ts
git commit -m "feat(ce-memory): advisory file locking for FileStore"
```

---

### Task 17: FileStore Locking (Python)

Mirror Task 16 for Python `FileStore` in `memory.py`. Use `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`.

- [ ] **Step 1-4: TDD cycle**
- [ ] **Step 5: Commit**

```bash
git commit -m "feat(python): advisory file locking for FileStore"
```

---

### Task 18: Python ContextSession Thread Safety

**Files:**

- Modify: `python/context_engineering/session.py`
- Modify: `python/tests/test_session.py`

- [ ] **Step 1: Write failing test for concurrent access**

Add to `python/tests/test_session.py`:

```python
import threading

def test_concurrent_compile_is_thread_safe():
    session = create_session(Budget(maxTokens=10000))
    for i in range(20):
        session.add_items([ContextItem(id=f"item-{i}", content=f"content {i}")])

    results = []
    errors = []

    def do_compile():
        try:
            result = session.compile()
            results.append(result)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_compile) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Thread errors: {errors}"
    assert len(results) == 10
    # All results should be consistent (same compile count progression)
```

- [ ] **Step 2: Run test — may pass or fail depending on timing**

- [ ] **Step 3: Add `threading.Lock` to `ContextSession`**

In `python/context_engineering/session.py`, add `self._lock = threading.Lock()` to `__init__`. Wrap `add_items`, `set_items`, `remove_items`, `compile`, `clear`, `item_count`, `get_compile_count` with `with self._lock:`. Note: `set_items` also mutates `_current_items` and must be locked.

- [ ] **Step 4: Run all session tests**

Run: `cd python && python -m pytest tests/test_session.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add python/context_engineering/session.py python/tests/test_session.py
git commit -m "feat(python): add thread safety to ContextSession"
```

---

## Final Verification

### Task 19: Full Test Suite Verification

- [ ] **Step 1: Run full TS test suite**

Run: `pnpm test:all`
Expected: ALL PASS (353+ tests)

- [ ] **Step 2: Run full Python test suite**

Run: `cd python && python -m pytest`
Expected: ALL PASS (487+ tests + new tests)

- [ ] **Step 3: Run TS type checking**

Run: `pnpm check:all`
Expected: No errors in ce-core and ce-memory

- [ ] **Step 4: Final commit if any cleanup needed**
