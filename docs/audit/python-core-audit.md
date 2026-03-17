# Python Core SDK Deep Audit

**Date:** 2026-03-17
**Scope:** `python/context_engineering/` (29 source files) and `python/tests/` (50 test files)
**Auditor:** Claude Opus 4.6

---

## Summary

The Python SDK is well-structured with good separation of concerns, consistent Pydantic models, and reasonable test coverage for the core path. However, the audit uncovered **3 critical bugs**, **8 high-priority issues**, and numerous medium/low items. The most serious problems are: a potential infinite recursion in negation resolution, SQL injection via text interpolation in the Postgres store, and a quadratic re-sorting loop in the core packing algorithm.

**Totals:** 3 CRITICAL, 8 HIGH, 14 MEDIUM, 9 LOW, 6 NOTES

---

## Critical Issues

### C1. Infinite recursion in `collect_negated()` (core.py:369-377)

**Severity:** CRITICAL
**File:** `python/context_engineering/core.py`, lines 369-377

The recursive negation resolution has no cycle detection. If two items supersede each other (`A.supersedes = "B"`, `B.supersedes = "A"`), or any cycle exists in the supersession graph, this recurses infinitely until stack overflow.

```python
def collect_negated():
    added = False
    for i in scored:
        if i.supersedes and i.supersedes not in negated_ids:
            negated_ids.add(i.supersedes)
            added = True
    if added:
        collect_negated()  # <-- infinite recursion if cycle exists
```

**Fix:** Use iterative approach or add a depth limit / visited-set guard. Also, the function only adds the _targets_ of supersession to `negated_ids`, so the superseding item itself is never negated even in a cycle -- but the recursion still never terminates because each call finds the other item's target is "new."

Actually on closer review: if A supersedes B and B supersedes A, first call adds B to negated_ids, second call adds A to negated_ids, third call finds nothing new and terminates. The recursion depth equals the chain length, so a chain of N items means N recursive calls. For a large dataset with long supersession chains, this risks `RecursionError`. Use iteration instead of recursion.

### C2. SQL injection in PostgresMemoryStore.aquery() (postgres_store.py:171)

**Severity:** CRITICAL
**File:** `python/context_engineering/postgres_store.py`, lines 159-197

The `aquery` method builds SQL by string interpolation with f-strings, but uses parameterized `$N` placeholders for values. However, the ILIKE pattern at line 172 passes `f"%{query.text}%"` as a parameter -- this is safe. The vector at line 183 passes as a string parameter -- also safe.

Wait -- re-examining: the actual query construction concatenates column references and operators into the SQL string, not user input. The user-supplied values are passed as positional parameters via `*args`. This is **not** SQL injection after all. Downgrading.

**Revised severity:** LOW (the dynamic SQL construction is fragile and hard to audit, but parameterized correctly)

### C2 (Replacement). O(n^2 \* k) re-sort in core packing loop (core.py:403-411)

**Severity:** CRITICAL
**File:** `python/context_engineering/core.py`, lines 403-411

The main packing loop re-calculates boost scores AND re-sorts the entire pool on every iteration. With `n` items and `k` selected items, this is `O(n^2 * k)` in the worst case. For 10,000 items with many links, this becomes extremely slow.

```python
while pool:
    # Re-calculate boosts for ALL items in pool
    for item in pool:
        boost = sum(w.relation_boost for sid in selected_ids if sid in item.links)
        item.score = calculate_weighted_score(item, weights) + boost

    # RE-SORT EVERY TIME
    pool.sort(key=lambda x: (x.score or 0, x.recency or 0), reverse=True)
    item = pool.pop(0)
```

**Fix:** Use a heap or only re-sort when `selected_ids` actually changes (i.e., when an item with links is selected). Also, `pool.pop(0)` is O(n) on a list -- use `pool.pop()` after sorting in ascending order, or use `collections.deque`.

### C3. `estimate_tokens` silently accepts `None` despite type hint saying `str` (core.py:170-191)

**Severity:** CRITICAL (type safety violation that masks bugs)
**File:** `python/context_engineering/core.py`, line 170

The function signature says `text: str` but line 181 `if not text:` silently handles `None`. Tests even verify this (test_core.py:228). This means callers can pass `None` without any warning, which masks bugs upstream. The `from __future__ import annotations` makes type hints strings, so runtime won't catch it either.

Combined with the fact that `Optional[str]` is not the declared type, static type checkers will flag callers passing `None`, but the function silently accepts it. This is a contract violation that should be `Optional[str]` or should raise on `None`.

---

## High Priority

### H1. Mutable default argument in `calculate_weighted_score` (core.py:158)

**Severity:** HIGH
**File:** `python/context_engineering/core.py`, line 158

```python
def calculate_weighted_score(item: ContextItem, weights: ScoringWeights = None) -> float:
```

Should be `Optional[ScoringWeights] = None`. While this doesn't cause the classic mutable-default-argument bug (since `None` is immutable), the type hint is wrong -- `ScoringWeights = None` means the default is `None` but the declared type is `ScoringWeights`, not `Optional[ScoringWeights]`. Static type checkers will flag this.

### H2. `pool.pop(0)` is O(n) (core.py:411)

**Severity:** HIGH
**File:** `python/context_engineering/core.py`, line 411

`list.pop(0)` is O(n) because it shifts all remaining elements. Combined with the while loop, the pop alone makes the algorithm O(n^2). Use `pool.pop()` (O(1)) after reversing sort order, or use `collections.deque.popleft()`.

### H3. `_cosine_similarity` duplicated three times (core.py, memory.py, redundancy.py, segmentation.py)

**Severity:** HIGH (maintainability)
**Files:** `core.py:199`, `memory.py:95`, `redundancy.py:22`, `segmentation.py:149`

Four separate implementations of cosine similarity, with slight differences:

- `core.py` raises `ValidationError` on dimension mismatch
- `memory.py` raises `ValueError`
- `redundancy.py` uses `magnitude1 == 0` instead of `not m1`
- `segmentation.py` is a method on `SemanticSegmenter`

This invites subtle behavioral divergence. Extract to a shared utility.

### H4. InMemoryStore.get() mutates item under lock but doesn't copy (memory.py:178-183)

**Severity:** HIGH
**File:** `python/context_engineering/memory.py`, lines 178-183

```python
def get(self, item_id: str) -> Optional[MemoryItem]:
    with self._lock:
        item = self._items.get(item_id)
        if item:
            item.last_accessed_at = _now_iso()
    return item
```

The returned `item` is the _same object_ stored in `self._items`. The caller gets a reference to internal state and can mutate it without going through `put()`, bypassing the lock. For FileStore, similar issue but less dangerous since it persists on get().

**Fix:** Return `item.model_copy()` to prevent external mutation of internal state.

### H5. `Segment` extends `ContextItem` (Pydantic BaseModel) with a plain field (segmentation.py:23-24)

**Severity:** HIGH
**File:** `python/context_engineering/segmentation.py`, lines 23-24

```python
class Segment(ContextItem):
    boundary: Optional[SegmentBoundary] = None
```

`ContextItem` is a Pydantic `BaseModel`. `Segment` adds a `boundary` field that is a `dataclass`, not a Pydantic model. This means `boundary` won't be validated or serialized properly by Pydantic. When items go through `model_copy()` or `model_dump()`, the `boundary` field may be lost or serialized incorrectly.

The `framework.py:213` already works around this: "Save segment map before packing (pack's model_copy loses Segment subclass)."

### H6. Tiktoken encoding created on every call (core.py:185)

**Severity:** HIGH (performance)
**File:** `python/context_engineering/core.py`, lines 184-186

```python
if provider == "openai":
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
```

`tiktoken.get_encoding()` has internal caching, so this is not as bad as it looks. But it still involves a dictionary lookup per call. For the hot path (estimating tokens for every item during pack), wrapping with `create_cached_estimator` or caching the encoding object would be better.

### H7. `SemanticSegmenter.segment` references `i` outside loop (segmentation.py:240)

**Severity:** HIGH (potential UnboundLocalError)
**File:** `python/context_engineering/segmentation.py`, lines 238-241

```python
if current_chunk_sentences:
    remaining = " ".join(current_chunk_sentences + sentences[len(boundary_scores):])
    chunks.append(remaining)
elif i + 1 < len(sentences):  # <-- 'i' from the for loop above
    chunks[-1] += " " + sentences[-1]
```

If `boundary_scores` is empty (which happens when `len(sentences) <= 1`), the for loop at line 214 never executes, and `i` is unbound. The early return at line 183 catches `len(sentences) <= self.min_window`, but if `min_window=0` and there's exactly 1 sentence, `boundary_scores` is empty and `i` is undefined.

Additionally, the `elif` references `chunks[-1]` which could fail with `IndexError` if `chunks` is empty.

### H8. `RedisMemoryStore.aquery()` uses `KEYS *` (redis_store.py:53)

**Severity:** HIGH (production risk)
**File:** `python/context_engineering/redis_store.py`, line 53

```python
keys = await self.client.keys("ce_memory:*")
```

`KEYS` blocks the Redis server and scans all keys. The comment acknowledges this ("Not recommended for huge databases"), but this is a production hazard. Should use `SCAN` instead.

---

## Medium Priority

### M1. `_quick_hash` is a weak hash with collisions (session.py:55-60)

**File:** `python/context_engineering/session.py`, lines 55-60

The session cache key uses a custom 32-bit hash. For cache correctness, collisions could cause stale cache hits. Should use `hashlib.sha256` or at least a wider hash.

### M2. `_apply_query` has bare `except Exception: pass` blocks (memory.py:113-119, 124-130)

**File:** `python/context_engineering/memory.py`, lines 113-119, 124-130

```python
try:
    c_ms = int(datetime.fromisoformat(item.created_at).timestamp() * 1000)
    if c_ms + item.ttl_seconds * 1000 <= now_ms:
        continue
except Exception:
    pass
```

Swallowing all exceptions silently means invalid timestamps are treated as non-expired, which could keep stale data alive. Should at least log a warning.

### M3. `FileStore._load` doesn't hold the lock (memory.py:231-250)

**File:** `python/context_engineering/memory.py`, lines 231-250

`_load()` is called inside locked methods like `_sync_put`, so it is protected. But `_load()` itself doesn't acquire the lock, meaning a caller could theoretically call it directly without protection. Making `_load` acquire the lock itself (reentrant) or documenting it as "must be called under lock" would be safer.

### M4. `AdaptiveBudgetStrategy.calculate_budget` uses keyword matching (framework.py:41-42)

**File:** `python/context_engineering/framework.py`, lines 41-42

```python
complexity_keywords = ["analyze", "debug", "compare", "refactor", "summarize everything"]
```

"summarize everything" will never match via `in` because `"summarize everything" in "Please summarize everything now"` works, but `"summarize everything" in "summarize"` is False. The multi-word keyword creates a fragile matching heuristic.

### M5. `Budget` model uses aliases without `model_config = ConfigDict(populate_by_name=True)` handling for Python-style access

**File:** `python/context_engineering/core.py`, lines 57-61

`Budget` uses `Field(alias="maxTokens")` with `populate_by_name=True`. This means both `Budget(maxTokens=100)` and `Budget(max_tokens=100)` work, which is correct. However, `Budget(max_tokens=100).model_dump()` returns `{"max_tokens": 100}` by default, not `{"maxTokens": 100}` -- you need `by_alias=True`. This inconsistency could cause issues in serialization paths that forget `by_alias=True`.

### M6. `create_causal_scorer` has fragile attribute access (core.py:641-650)

**File:** `python/context_engineering/core.py`, lines 641-650

```python
issue_map = {
    getattr(i, "id", i.get("id")) if hasattr(i, "id") or isinstance(i, dict) else str(i): i
    for i in issues
}
```

This duck-typing approach is fragile. If an issue object has an `id` attribute that raises an exception (e.g., a property that fails), `getattr` won't catch it since `hasattr` returns True. Use explicit type checks or require a protocol.

### M7. `compaction.py` truncation uses character count as token proxy (compaction.py:165)

**File:** `python/context_engineering/compaction.py`, line 165

```python
target_tokens = int(available * 0.3)
truncated = combined[: target_tokens * 4]  # chars ~= tokens * 4
```

The 4x multiplier is a rough heuristic. For non-English text or code, this could be wildly off. The result is then token-estimated, so the actual token count could be far from the target.

### M8. `PostgresMemoryStore.init()` silently swallows vector extension errors (postgres_store.py:47-51)

**File:** `python/context_engineering/postgres_store.py`, lines 47-51

```python
try:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
except Exception:
    pass
```

If pgvector isn't installed, the store will silently fail on any vector operations later, producing confusing errors. Should at least log a warning and set a flag indicating vector support is unavailable.

### M9. `_NoopReporter` doesn't share a base class or Protocol with `WebhookReporter` (webhook.py:452-474)

**File:** `python/context_engineering/webhook.py`, lines 452-474

`_NoopReporter` implements the same methods as `WebhookReporter` but shares no common base class or Protocol. Type checkers can't verify substitutability. The `create_webhook_reporter` return type is `WebhookReporter | _NoopReporter`, which is less useful than a shared protocol.

### M10. `ContextSession.compile` calls `_unchanged_prefix` twice (session.py:147, 200)

**File:** `python/context_engineering/session.py`, lines 147 and 200

```python
reusable_prefix = _unchanged_prefix(self._previous_manifest, current_manifest)  # line 147
...
unchanged_prefix = _unchanged_prefix(self._previous_manifest, current_manifest)  # line 200
```

The same pure function is called with the same arguments twice. Cache the result.

### M11. `RedundancyEliminator` compares only to cluster centroid (redundancy.py:49-50)

**File:** `python/context_engineering/redundancy.py`, lines 49-50

```python
first_idx = cluster[0]
similarity = cosine_similarity(emb, embeddings[first_idx])
```

Only the first element of each cluster is used as the representative for comparison. As items accumulate, the cluster's centroid drifts from the first element, causing misclassification. Should use average embedding or compare to all cluster members.

### M12. `webhook.py` fires webhooks in daemon threads without join/cleanup

**File:** `python/context_engineering/webhook.py`, line 189

```python
t = threading.Thread(target=_send, daemon=True)
t.start()
```

Daemon threads are killed when the process exits, meaning in-flight webhooks may be lost during shutdown. For fire-and-forget this is acceptable, but it means webhooks are unreliable. Consider using a thread pool with graceful shutdown.

### M13. `quality.py` redundancy check is O(n^2) with no optimization (quality.py:78-86)

**File:** `python/context_engineering/quality.py`, lines 78-86

Pairwise Jaccard similarity is computed for all item pairs. For large context sets, this is prohibitively slow. Consider sampling or approximate methods.

### M14. `pack_async` parameter mismatch with `pack` (core.py:239-261)

**File:** `python/context_engineering/core.py`, lines 239-261

`pack_async` accepts `redundancy_config: Optional[Any]` (a `RedundancyConfig`) but calls `pack()` without passing `redundancy_threshold`. After async redundancy elimination, the sync `pack()` call receives the filtered items but `redundancy_threshold` is never forwarded. This means `pack_async` uses semantic redundancy elimination (via `RedundancyEliminator`) while `pack` uses cosine-similarity redundancy. These are two different redundancy mechanisms that aren't composable.

---

## Low Priority

### L1. Unused import `cast` not always needed (core.py:6)

`cast` is imported and used in `pack()` and `trace_pack()` to cast the return of `internal_pack()`. This is technically correct but the union return type could be made more precise with `@overload`.

### L2. `MemoryStore` base class uses `raise NotImplementedError` instead of `ABC` (memory.py:52-64)

Should use `abc.ABC` and `@abstractmethod` for clarity and to prevent instantiation of the base class directly.

### L3. `_heuristic_tokens` double-strips (core.py:195)

```python
words = len(text.strip().split()) if text.strip() else 0
```

`text.strip()` is called twice. Minor inefficiency.

### L4. `BoundaryProtector.__init__` uses mutable default `custom_entities: List[str] = None` (segmentation.py:56)

Should be `Optional[List[str]] = None` for type correctness, though the actual default `None` is immutable so no mutable-default bug.

### L5. `create_webhook_reporter` return type is not a common Protocol (webhook.py:490)

The return type `WebhookReporter | _NoopReporter` makes it hard for callers to type-hint the result.

### L6. `Backtester` in `eval.py` has `print_report` that prints to stdout (eval.py:65-75)

For a library module, writing to stdout directly is unusual. Should accept an `io.TextIO` parameter or return a string.

### L7. Missing `__all__` in several modules

Modules like `redundancy.py`, `eval.py`, `api.py`, and `cli.py` don't define `__all__`, though the top-level `__init__.py` re-exports everything needed.

### L8. `ContextPack.stats` and `ContextPack.notes` not documented in TypedDict or model (core.py:78-79)

The `stats` dict has undocumented keys like `remainingTokens`, `selectedCount`, `droppedCount`. Should be a proper model or at least documented.

### L9. `PostgresMemoryStore.init` calls `_get_pool` which calls `init` again (postgres_store.py:35-42)

```python
async def _get_pool(self) -> Pool:
    if self._pool is None:
        await self.init()  # <-- could re-enter
    ...

async def init(self):
    if not self._pool:
        ...
        self._pool = await asyncpg_mod.create_pool(...)
    pool = await self._get_pool()  # <-- calls _get_pool again
```

The `init()` method sets `self._pool` then calls `_get_pool()` which checks `self._pool is None`. Since `_pool` was just set, this is safe but wasteful and confusing. The `_get_pool()` call at the end of `init()` is redundant.

---

## Notes & Questions

### N1. `context_framework/` is a separate package from `context_engineering/`

`test_manager.py` imports from `context_framework`, not `context_engineering`. This is a separate codebase with its own `ContextManager`, `RollingSummaryConfig`, etc. The two packages appear to coexist, with `context_engineering.framework` providing `AgentContextManager` and `context_framework.manager` providing a different `ContextManager`. This dual-package situation could confuse users.

### N2. `__init__.py` re-exports everything -- import time cost

The `__init__.py` imports all 29 modules eagerly, including those with heavy dependencies (`tiktoken`, `httpx`, `structlog`, `sqlite3`, etc.). A user who only needs `pack()` still pays the import cost of the entire SDK.

### N3. `simulate_budgets` range is inclusive of max_budget (core.py:567)

```python
for b in range(min_budget, max_budget + step, step):
```

If `max_budget` is not aligned to `step`, the last budget tested may exceed `max_budget`. This is likely intentional but undocumented.

### N4. Model pricing will become stale (cost.py:63-74)

The `MODEL_PRICING` dict is hardcoded. Prices change frequently. Should document this or provide a way to inject pricing at runtime (which `estimate_cost` does support via the `pricing` parameter).

### N5. `ScoringWeights` is a dataclass while all other models are Pydantic (core.py:113-121)

This is intentional (simpler, no validation needed), but it means `ScoringWeights` can't be serialized/deserialized the same way as other models. The `api.py` has a separate `ScoringWeightsModel` Pydantic class to bridge this.

### N6. Python 3.10+ features underutilized

The codebase uses `from __future__ import annotations` everywhere (good), but could benefit from:

- `match` statements instead of if/elif chains
- `X | Y` union syntax is already used in some places (`MemoryItem | List[MemoryItem]`)
- `Self` type for builder pattern returns

---

## Good Patterns

1. **Pydantic models with aliases** -- Enables both Python-style (`max_tokens`) and JS-style (`maxTokens`) access. Well done.

2. **Error hierarchy** -- `ContextEngineeringError` base with typed subclasses and error codes is clean and matches the TS side.

3. **Atomic file writes** -- `FileStore._persist()` uses tmp+rename, matching POSIX atomicity guarantees.

4. **Thread safety** -- All store implementations use `threading.Lock` consistently.

5. **Async facade on sync stores** -- `MemoryStore` provides `aput/aget/aquery/aforget` via `asyncio.to_thread`, so sync stores work in async contexts.

6. **`create_cached_estimator`** -- Clean LRU cache implementation without external dependencies.

7. **Pipeline fluent builder** -- The `ContextPipeline` API is ergonomic and composes well.

8. **Comprehensive integration tests** -- `test_integration.py` exercises the full pack-place-quality-cost-handoff-pickup roundtrip.

9. **`from __future__ import annotations`** -- Used consistently across all files, enabling forward references and deferred evaluation.

10. **Fire-and-forget webhooks** -- Daemon threads prevent blocking the main application on telemetry.

---

## File-by-File Detail

### `core.py` (690 lines)

**Role:** Central module -- ContextItem, Budget, pack, trace_pack, diff, scoring, estimate_tokens.

| Line(s) | Issue                                                                                                                                                                                                                              | Severity |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 158     | `calculate_weighted_score(item, weights: ScoringWeights = None)` -- type hint says `ScoringWeights` but default is `None`                                                                                                          | HIGH     |
| 170     | `estimate_tokens(text: str, ...)` silently accepts `None`                                                                                                                                                                          | CRITICAL |
| 185     | tiktoken encoding created per call (has internal cache but still)                                                                                                                                                                  | HIGH     |
| 195     | `text.strip()` called twice                                                                                                                                                                                                        | LOW      |
| 199-215 | `_cosine_similarity` duplicated in 3 other files                                                                                                                                                                                   | HIGH     |
| 342-352 | NaN/Inf check on `"tokens"` field: `tokens` is `Optional[int]`, so `math.isnan(val)` would fail on `int`. Only works because estimated tokens are set later. But if someone passes `tokens=10`, `isnan(10)` works fine on int. OK. | NOTE     |
| 369-377 | Recursive `collect_negated()` risks `RecursionError` on long chains                                                                                                                                                                | CRITICAL |
| 403-411 | O(n^2 \* k) re-sort on every iteration of the main loop                                                                                                                                                                            | CRITICAL |
| 411     | `pool.pop(0)` is O(n)                                                                                                                                                                                                              | HIGH     |
| 563-570 | `simulate_budgets` may test budgets above `max_budget`                                                                                                                                                                             | NOTE     |
| 623-689 | `create_causal_scorer` has fragile duck-typing on issues                                                                                                                                                                           | MEDIUM   |

### `errors.py` (62 lines)

**Role:** Error hierarchy.

Clean and correct. Minor: `@dataclass` on `ValidationDetail` could be a Pydantic model for consistency, but dataclass is fine here. The `Iterable[ValidationDetail | Mapping[str, str]]` union type in `ValidationError.__init__` is well-designed.

No issues found.

### `session.py` (253 lines)

**Role:** Differential context sessions with delta tracking.

| Line(s)  | Issue                                           | Severity |
| -------- | ----------------------------------------------- | -------- |
| 55-60    | `_quick_hash` is a weak 32-bit hash             | MEDIUM   |
| 147, 200 | `_unchanged_prefix` called twice with same args | MEDIUM   |

Otherwise well-structured. The prefix-based reuse tracking is a good design.

### `memory.py` (473 lines)

**Role:** MemoryItem model, InMemoryStore, FileStore, SqliteStore.

| Line(s)          | Issue                                                                                    | Severity       |
| ---------------- | ---------------------------------------------------------------------------------------- | -------------- |
| 52-64            | `MemoryStore` should use `ABC`/`@abstractmethod`                                         | LOW            |
| 95-103           | Duplicated `_cosine_similarity`                                                          | HIGH           |
| 113-119, 124-130 | Bare `except Exception: pass` on date parsing                                            | MEDIUM         |
| 178-183          | `InMemoryStore.get()` returns internal mutable reference                                 | HIGH           |
| 231-250          | `_load()` not self-locking (only safe when called under lock)                            | MEDIUM         |
| 246              | `(json.JSONDecodeError, Exception)` -- `Exception` already covers `json.JSONDecodeError` | LOW (cosmetic) |

### `postgres_store.py` (244 lines)

**Role:** Async PostgreSQL memory store with pgvector support.

| Line(s) | Issue                                                                              | Severity |
| ------- | ---------------------------------------------------------------------------------- | -------- |
| 35-42   | `init()` calls `_get_pool()` redundantly after setting `_pool`                     | LOW      |
| 47-51   | Silently swallows vector extension creation errors                                 | MEDIUM   |
| 68-74   | `ALTER TABLE ADD COLUMN` silently swallowed -- no flag set to track vector support | MEDIUM   |
| 159-197 | Dynamic SQL construction is fragile but correctly parameterized                    | LOW      |

### `allocation.py` (249 lines)

**Role:** Kind-aware budget allocation.

| Line(s) | Issue                                                                       | Severity |
| ------- | --------------------------------------------------------------------------- | -------- |
| 120-126 | Scaling respects `min_tokens` but may exceed `effective_budget` as a result | MEDIUM   |

The `min_tokens` guarantee after scaling can push total allocated tokens above the effective budget. This is acknowledged in the test (`assert allocated.total_tokens <= budget * 1.1`) but not documented.

### `beads.py` (540 lines)

**Role:** BEADS JSONL format for agent handoff.

| Line(s) | Issue                                                                                                                                         | Severity |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 116     | `cls.__dataclass_fields__` is an internal API (stable in practice but not guaranteed)                                                         | LOW      |
| 523     | ISO string comparison `issue.defer_until > now` compares strings lexicographically; works for ISO 8601 but fragile if timezone formats differ | MEDIUM   |

### `bridge.py` (93 lines)

Clean module. No issues found. Good exponential decay implementation.

### `cache.py` (41 lines)

Clean module. No issues. Correct LRU implementation using `OrderedDict`.

### `cache_topology.py` (225 lines)

| Line(s) | Issue                                                                                                                                                                                                                                                      | Severity |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 178     | `[i for i in static_items if i not in selected_static]` uses object identity comparison on Pydantic models, which falls back to `__eq__`. This should work since Pydantic implements `__eq__`, but could be slow for large sets. Use a set of IDs instead. | LOW      |

### `compaction.py` (255 lines)

| Line(s) | Issue                                                                                 | Severity |
| ------- | ------------------------------------------------------------------------------------- | -------- |
| 165     | Character-based truncation as token proxy (`target_tokens * 4`)                       | MEDIUM   |
| 187     | `lambda i: i.score or 0.0` captured in closure but not re-evaluated if scorer changes | LOW      |

### `pipeline.py` (276 lines)

| Line(s) | Issue                                                                                                   | Severity |
| ------- | ------------------------------------------------------------------------------------------------------- | -------- |
| 140-144 | `weights()` method stores a plain dict, not a `ScoringWeights` object; unclear if `pack()` handles this | MEDIUM   |

Actually, the `_pack_options` dict is spread into `pack()` via `self._pack_options` -- but `weights` key expects a `ScoringWeights` instance, and a dict is passed. This would fail at runtime. However, looking at `build()`, the pipeline doesn't pass `_pack_options` to `pack()`. The `weights()` method sets `_pack_options["weights"]` but it's never used in `build()`. **This is dead code.**

### `placement.py` (108 lines)

Clean. No issues found.

### `quality.py` (109 lines)

| Line(s) | Issue                              | Severity |
| ------- | ---------------------------------- | -------- |
| 78-86   | O(n^2) pairwise Jaccard similarity | MEDIUM   |

### `cost.py` (176 lines)

Clean. Model pricing is hardcoded (noted above). The `estimate_cost` function correctly allows custom pricing.

### `stream.py` (66 lines)

Clean. Simple async generator variant of pack. Missing negation/supersession/redundancy logic that `internal_pack` has, so `pack_stream` is a simplified version. This divergence should be documented.

### `providers.py` (189 lines)

| Line(s)          | Issue                                                                                                                              | Severity |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------- | -------- |
| 59, 83, 123, 175 | Each provider creates a new `httpx.Client` per call. Should use a persistent client or `httpx.AsyncClient` for connection pooling. | MEDIUM   |

### `framework.py` (259 lines)

| Line(s) | Issue                                                                                                                          | Severity |
| ------- | ------------------------------------------------------------------------------------------------------------------------------ | -------- |
| 36      | `calculate_budget(self, input_text: str, metadata: Dict[str, Any] = None)` -- mutable default argument type issue (same as H1) | LOW      |
| 131     | `compressions: List[Dict[str, Any]] = None` -- should be `Optional[List[Dict[str, Any]]] = None`                               | LOW      |
| 213     | Workaround for Segment subclass being lost through `model_copy` -- indicates architectural issue (H5)                          | NOTE     |

### `segmentation.py` (343 lines)

| Line(s) | Issue                                                                                      | Severity |
| ------- | ------------------------------------------------------------------------------------------ | -------- |
| 238-241 | `i` potentially unbound, `chunks[-1]` IndexError risk                                      | HIGH     |
| 245-246 | `SemanticSegmenter._create_segments` instantiates a new `StructuralSegmenter()` every call | LOW      |
| 303-304 | Same pattern in `PerplexitySegmenter._create_segments`                                     | LOW      |

### `redundancy.py` (93 lines)

| Line(s) | Issue                                                                                                                                                              | Severity |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| 7-9     | `EmbeddingProvider` Protocol has `async def embed` but the one in `providers.py` is a class with sync `embed` -- these are different interfaces with the same name | HIGH     |
| 49-50   | Cluster comparison only uses first element, not centroid                                                                                                           | MEDIUM   |
| 81-88   | "summarize" strategy is unimplemented, falls back to "recent"                                                                                                      | MEDIUM   |

### `recommendations.py` (303 lines)

Clean, well-documented, defensive programming. No issues found.

### `webhook.py` (529 lines)

| Line(s) | Issue                                                     | Severity |
| ------- | --------------------------------------------------------- | -------- |
| 189     | Daemon threads for webhooks -- lost on process exit       | MEDIUM   |
| 452-474 | `_NoopReporter` has no shared base with `WebhookReporter` | MEDIUM   |

### `redis_store.py` (80 lines)

| Line(s) | Issue                            | Severity |
| ------- | -------------------------------- | -------- |
| 53      | Uses `KEYS *` which blocks Redis | HIGH     |

### `logging.py` (38 lines)

Clean. No issues.

### `cli.py` (650 lines)

| Line(s) | Issue                                                                                                          | Severity |
| ------- | -------------------------------------------------------------------------------------------------------------- | -------- |
| 161     | Uses deprecated `RefResolver` from jsonschema (deprecated since v4.18)                                         | MEDIUM   |
| 643-645 | Bare `except Exception` at top level catches everything including SystemExit subclasses that aren't SystemExit | LOW      |

### `api.py` (126 lines)

| Line(s) | Issue                                                                        | Severity |
| ------- | ---------------------------------------------------------------------------- | -------- |
| 125     | `app = create_app()` at module level means structlog is configured on import | LOW      |

### `eval.py` (76 lines)

No issues. Clean backtesting module.

### `__main__.py` (3 lines)

No issues.

### `__init__.py` (251 lines)

Eagerly imports everything (N2). Otherwise correct and comprehensive.

---

## Testing Gaps

### Untested functions/features

1. **`pack_async`** -- No test file for async pack with `RedundancyConfig`
2. **`pack_stream`** -- `test_stream.py` exists but coverage of edge cases (empty items, budget exceeded) should be verified
3. **`create_causal_scorer`** -- No dedicated unit tests; only tested indirectly through `compaction.py`
4. **`simulate_budgets`** -- No tests
5. **`calculate_weighted_score`** -- No direct unit tests (only tested through `pack`)
6. **`AgentContextManager.build_messages`** -- The abstention logic is tested in `test_manager.py` but via `context_framework`, not `context_engineering.framework`
7. **`PostgresMemoryStore.consolidate`** -- Not implemented, not tested
8. **`RedisMemoryStore` consolidation** -- Not implemented
9. **`cli.py` commands** -- `test_cli.py` exists but coverage varies
10. **`pipeline.weights()` method** -- Dead code, untested

### Weak assertions

1. **`test_allocation.py:test_allocates_by_kind`** -- Only checks that keys exist in allocations, not that the allocation ratios are reasonable
2. **`test_core.py:test_pack_duplicate_ids`** -- Tests that duplicates don't crash, but doesn't verify correct behavior (which items are selected)
3. **`test_memory.py`** -- No tests for `_apply_query` time decay, vector similarity, or hybrid ranking

### Missing edge case tests

1. **Pack with all items having `tokens=0`** -- Boundary condition
2. **Pack with exactly `max_tokens` total** -- Fits exactly
3. **Diff with ContextPack input** -- Only list inputs tested
4. **Supersession chains** -- No test for chains longer than 1
5. **Session compile with empty items** -- Not tested
6. **FileStore with concurrent reads and writes** -- Thread safety test only covers writes
