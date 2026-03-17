# Python Framework Deep Audit

**Scope:** `python/context_framework/` -- 29 source files, ~23,500 lines
**Date:** 2026-03-17
**Auditor:** Claude Opus 4.6 (automated deep review)

---

## Summary

The `context_framework` package is a large Python-only layer providing:

1. A budget-aware `ContextManager` for LLM prompt assembly
2. Scoring, retrieval, and summarization primitives
3. Provider adapter bridges (OpenAI, Anthropic, Cerebras, Ollama)
4. A `TriProviderPipeline` orchestrator with 14 use-case specs
5. Twelve domain-specific "Commander" runtimes (SOC, AML, Claims, Supply Chain, etc.)
6. Framework bridges (LangGraph, DeepAgents, PydanticAI)

**Overall:** The core layer (`manager.py`, `models.py`, `scoring.py`, `retrieval.py`, `tokenizer.py`, `summarization.py`) is solid, well-typed, and thoughtfully designed. The twelve domain runtimes, however, suffer from extreme copy-paste duplication -- roughly 15,000 lines of near-identical boilerplate. This is the dominant issue in the codebase.

**Critical:** 1 | **High:** 8 | **Medium:** 12 | **Low:** 9 | **Notes:** 6

---

## Critical Issues

### C1. Module-level side effect in `tri_provider_use_cases.py` (line 557)

```python
validate_use_case_catalog()
```

This validation function runs **at import time**, meaning every `import context_framework` executes validation logic including iteration over all 14 specs with threshold checks. If any spec fails validation (e.g., during development), the entire package becomes unimportable. This also means the validation cost is paid on every import in every test, CLI invocation, and library consumer.

**File:** `tri_provider_use_cases.py:557`
**Fix:** Move to an explicit `validate()` call, or guard behind `if __name__ == "__main__"`, or make it lazy.

---

## High Priority

### H1. Massive code duplication across 12+ runtime files

The following identical patterns are copy-pasted across 13 files:

| Pattern                                                                                                                                | Instances                                                     |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `_HTTPJSONAdapterBase` (identical class, ~30 lines each)                                                                               | 13                                                            |
| `_unique_preserve()` (identical function)                                                                                              | 13                                                            |
| `_ExecutionTask` dataclass (identical)                                                                                                 | 12                                                            |
| `_execute_tasks()` / `_execute_task()` / `_execute_with_retry()` / `_is_retryable_error()` (near-identical, ~80 lines each)            | 12                                                            |
| `_safe_payload()` (identical static method)                                                                                            | 12                                                            |
| `_log_audit_event()` (near-identical)                                                                                                  | 12                                                            |
| `AuditLogger` / `IdempotencyStore` / `NoOpAuditLogger` / `JSONLAuditLogger` / `InMemoryIdempotencyStore` protocols and implementations | 2+ (soc_runtime + claims_runtime redefine them independently) |

**Impact:** ~8,000-10,000 lines of duplicated code. Every bug fix must be applied 12+ times. Any drift between copies becomes a silent behavioral inconsistency.

**Files:** All `*_runtime.py` files
**Fix:** Extract shared infrastructure into a `runtime_base.py` module:

- `_HTTPJSONAdapterBase`
- `_unique_preserve()`
- `_ExecutionTask`
- A `BaseCommander` class with `_execute_tasks`, `_execute_with_retry`, `_is_retryable_error`, `_safe_payload`, `_log_audit_event`
- Move `AuditLogger`, `IdempotencyStore`, and their implementations to a single location (they already exist in `soc_runtime.py` and are imported by `aml_runtime.py` and `supply_chain_runtime.py`, but `claims_runtime.py` redefines them independently)

### H2. `claims_runtime.py` redefines shared protocols independently

`claims_runtime.py` (lines 60-109) defines its own `AuditLogger`, `IdempotencyStore`, `NoOpAuditLogger`, `JSONLAuditLogger`, and `InMemoryIdempotencyStore` -- all identical to the ones in `soc_runtime.py`. Meanwhile, `aml_runtime.py` and `supply_chain_runtime.py` correctly import from `soc_runtime`.

**Impact:** Two independent type hierarchies for the same concepts. A caller passing a `soc_runtime.JSONLAuditLogger` to `CatastropheClaimsCommander` would work at runtime (duck typing) but would fail static type checking.

**File:** `claims_runtime.py:60-109`
**Fix:** Import from `soc_runtime` like the other runtimes do.

### H3. `EmbeddingScorer` cache grows unboundedly

```python
# scoring.py:59
_cache: dict[str, tuple[float, ...]] = field(default_factory=dict)
```

The `_cache` dictionary uses the full text as the key and stores the embedding vector. In a long-running process with varied content, this will grow without bound. There is no eviction policy, no size limit, and no way to clear it.

**File:** `scoring.py:59`
**Fix:** Use an LRU cache (e.g., `functools.lru_cache` or a bounded dict) with a configurable `max_cache_size`.

### H4. `__init__.py` is a 747-line enumeration of every symbol

The `__init__.py` eagerly imports every class, function, and constant from every submodule, including all 12 runtime modules. This means `import context_framework` loads all 23,000+ lines of code, all regex compilations, and the module-level `validate_use_case_catalog()` call.

**File:** `__init__.py` (all 747 lines)
**Impact:** Slow import time, especially for users who only need the core `ContextManager`.
**Fix:** Use lazy imports (`__getattr__` on the module) or split into sub-packages (`context_framework.runtimes`, `context_framework.bridges`).

### H5. `OllamaChatAdapter.request()` cloud/native branches are identical

```python
# providers.py:108-134
def request(self, packet, *, model, stream=False, cloud_mode=None, **extra):
    use_cloud = self.cloud_mode if cloud_mode is None else cloud_mode
    messages = self.messages(packet)
    if use_cloud:
        payload = {"model": model, "messages": messages, "stream": stream}
        payload.update(extra)
        return payload
    # Native path is identical:
    payload = {"model": model, "messages": messages, "stream": stream}
    payload.update(extra)
    return payload
```

Both branches produce the exact same output. The `cloud_mode` flag has no effect.

**File:** `providers.py:108-134`
**Fix:** Remove the dead branch or implement the actual native/cloud differences (native Ollama uses different keys, e.g., `options` instead of `temperature`).

### H6. `ApproxTokenCounter` returns `min_tokens` for empty strings

```python
# tokenizer.py:26-28
def count(self, text: str) -> int:
    body = text.strip()
    if not body:
        return self._min_tokens  # returns 1 for empty string
```

Empty text returns 1 token, which can cause the truncation binary search in `manager.py` to produce incorrect results. If an item's text is empty, it should logically be 0 tokens.

**File:** `tokenizer.py:26-28`
**Fix:** Return 0 for empty/whitespace-only text.

### H7. Binary search truncation can produce suboptimal results

In both `manager.py:607-625` and `summarization.py:87-100`, the truncation uses a binary search over character positions, calling `token_counter.count()` at each step. With `ApproxTokenCounter`, this is `O(log(n))` calls, but:

1. The search appends "..." only when `mid < len(text)`, meaning the ellipsis token cost is not accounted for in the final `best` selection when `mid == len(text)`.
2. The method calls `token_counter.count(best)` again after the loop, which is redundant when `best` was already measured inside the loop.

**Files:** `manager.py:607-625`, `summarization.py:87-100`
**Impact:** Minor inefficiency and potential off-by-one in token counting.

### H8. `_recency_score` has a redundant guard

```python
# manager.py:636-644
@staticmethod
def _recency_score(created_at, oldest, newest):
    if newest <= oldest:
        return 1.0
    total_window = (newest - oldest).total_seconds()
    age_position = (created_at - oldest).total_seconds()
    if total_window <= 0:  # This can never be true if newest > oldest
        return 1.0
    return max(0.0, min(1.0, age_position / total_window))
```

The second `total_window <= 0` check is unreachable because the first guard already handles `newest <= oldest`.

**File:** `manager.py:640-643`

---

## Medium Priority

### M1. No input validation on `ContextItem.text`

`ContextItem` accepts any string, including empty strings. An empty-text item will:

- Pass through `add_system`/`add_message` etc. without warning
- Count as 1 token (from `ApproxTokenCounter`)
- Consume a budget slot

**File:** `models.py:19-33`

### M2. `ContextItem.importance` silently clamps instead of warning

```python
# models.py:32-33
def __post_init__(self):
    self.importance = min(1.0, max(0.0, self.importance))
```

Out-of-range values are silently clamped. This can hide bugs where callers accidentally pass `importance=100` (meaning 100%) and get 1.0.

**File:** `models.py:32-33`

### M3. `ChromaRetriever` assumes L2 distance metric

```python
# retrieval.py:109
score = 1.0 - distance
```

This conversion assumes the Chroma collection uses L2 distance. If the collection uses cosine distance or inner product, this calculation produces incorrect scores.

**File:** `retrieval.py:109`

### M4. `QuoteOnlyFaithfulnessJudge` uses exact substring match without normalization

```python
# quality.py:87
if normalized_claim in normalized_context:
```

This is case-sensitive and whitespace-sensitive. "The cat sat" would not match "the cat sat" or "The cat sat". For a faithfulness judge, this is overly brittle.

**File:** `quality.py:83-93`

### M5. `HeuristicConversationSummarizer` uses `assert` for runtime invariant

```python
# summarization.py:83
assert self.token_counter is not None
```

Assertions are stripped in optimized mode (`python -O`). This should be a proper `if` check or the field should be non-optional.

**File:** `summarization.py:83`

### M6. `TriProviderPipeline._run_live` creates fresh SDK clients per call

```python
# tri_provider_pipeline.py:347-349
from openai import OpenAI
client = OpenAI()
```

Every live run creates a new `OpenAI()`, `Anthropic()`, and `Cerebras()` client. These clients typically maintain connection pools and should be reused. The import-inside-function pattern is fine for optionality, but client creation should be lifted.

**File:** `tri_provider_pipeline.py:347-402`

### M7. `_resolve_awaitable` in `framework_bridges.py` calls `asyncio.run()` which cannot be nested

```python
# framework_bridges.py:19-31
def _resolve_awaitable(value):
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError(...)
```

If there is no running loop, it calls `asyncio.run()`. But `asyncio.run()` cannot be called from within another `asyncio.run()`. In Jupyter notebooks or async contexts, this will raise a confusing error.

**File:** `framework_bridges.py:19-31`

### M8. `InMemorySIEMAdapter.query` only matches first 3 query terms

```python
# soc_runtime.py:138
if all(term in haystack for term in query_terms[:3]):
```

Silently drops query terms beyond the first 3, which could miss important filter criteria.

**File:** `soc_runtime.py:138`

### M9. `SOCIncidentCommander._is_high_risk` uses substring matching that is too broad

```python
# soc_runtime.py:521-531
return any(
    token in corpus
    for token in ("critical", "high", "compromise", ...)
)
```

The word "high" matches any text containing "high" as a substring (e.g., "highway", "higher", "highlight"). Same for "active incident" -- it matches "proactive incident".

**File:** `soc_runtime.py:521-531`

### M10. `_HOST_RE` regex in `soc_runtime.py` is too broad

```python
# soc_runtime.py:21
_HOST_RE = re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9.-]{2,63}\b")
```

This matches almost any word containing a dot, including "e.g.", "i.e.", version numbers like "3.11", and domain-like fragments. The filter `"." in value and "@" not in value and not _IP_RE.fullmatch(value)` on line 489 helps but is not sufficient.

**File:** `soc_runtime.py:21`

### M11. `build_messages` abstention logic has a subtle gap

```python
# manager.py:483-485
evidence_items = [item for item in packet.items if item.kind in CONFIDENCE_EVIDENCE_KINDS]
evidence_confidence = max(
    [getattr(i, "importance", 0.0) or 0.0 for i in evidence_items] + [0.0]
)
```

When there are zero evidence items, `evidence_confidence` is 0.0. This causes abstention even if the system context is sufficient. The `or 0.0` guard handles `None` but `importance` is always a float (clamped in `__post_init__`), so `or 0.0` would also convert `importance=0.0` to `0.0` -- which is correct but the `or` operator is misleading since it converts any falsy value.

**File:** `manager.py:483-485`

### M12. `RollingSummaryConfig.validate()` does not check `keep_recent_messages < trigger_messages`

If `keep_recent_messages >= trigger_messages`, the rolling summary will never actually prune anything because the cutoff computation in `_maybe_rollup_conversation` would be <= 0.

**File:** `summarization.py:28-34`

---

## Low Priority

### L1. `structlog` dependency is imported but only used for logging in `manager.py`

```python
# manager.py:7
import structlog
logger = structlog.get_logger(__name__)
```

Only used in `build_messages()`. If `structlog` is not installed, the entire framework fails to import. Consider making it optional or using stdlib `logging`.

**File:** `manager.py:7`

### L2. `ContextPacket.as_messages()` hardcodes "system" role for non-message items

```python
# models.py:56
role = item.role if item.kind == ContextKind.MESSAGE else "system"
```

For Anthropic, all non-user/assistant messages must go into the system prompt. This hardcoded "system" role is only correct for OpenAI-style APIs.

**File:** `models.py:56`

### L3. `cosine_similarity` uses `strict=True` in zip (good) but does manual norm computation

The implementation is correct but could use `math.sqrt(sum(...))` which it already does. For large vectors, numpy would be significantly faster. This is a minor performance note for embedding-heavy workloads.

**File:** `scoring.py:40-49`

### L4. `PineconeRetriever` uses `list()` instead of `tuple()` for vector

```python
# retrieval.py:153
vector = list(float(v) for v in self._embed(query))
```

Minor inconsistency -- `InMemoryVectorRetriever` uses `tuple()` for vectors.

**File:** `retrieval.py:153`

### L5. `_SimpleBM25` stores redundant `_corpus` field

The `_corpus` list is stored but only used during `__init__` to compute `_tfs` and `_doc_lens`. After construction, it is dead memory.

**File:** `hybrid_retrieval.py:26`

### L6. `OllamaSDKBridge.from_env()` does not validate `base_url`

The URL is read from env without any validation. A malformed URL will only fail at request time.

**File:** `provider_sdk.py:586-594`

### L7. `SpeculativeDecodingMetrics.rejection_rate` is a property while fields are frozen slots

This is fine functionally, but the asymmetry between stored `acceptance_rate` and computed `rejection_rate` is not documented.

**File:** `provider_sdk.py:300-302`

### L8. `AnthropicAgenticTextSystem.collect_text` accepts role `None`

```python
# anthropic_agentic_text_system.py:359
if role not in (None, "assistant"):
    continue
```

Messages with `role=None` are treated the same as `role="assistant"`, which may not be intentional.

**File:** `anthropic_agentic_text_system.py:359`

### L9. `ContextManager.clear()` does not reset token counts

After `clear()`, if items are re-added, any cached `token_count` from before the clear is preserved on items still referenced externally.

**File:** `manager.py:203-208`

---

## Notes & Questions

### N1. The `Retriever` Protocol does not define `__init__` or document expected lifecycle

All retrievers are stateful (hold embeddings, connection pools) but the protocol only defines `retrieve()`. There is no `close()` or cleanup method.

### N2. The `TriProviderPipeline` dry-run simulation is deterministic but domain-agnostic

The `_simulate_openai_extraction` and `_simulate_anthropic_plan` methods return the same canned text regardless of domain. This means dry-run reports all look similar regardless of the use case.

### N3. `_as_float` helper in `aml_runtime.py` auto-divides values > 1.0 by 100

```python
# aml_runtime.py:1051-1052
if cap_1 and out > 1.0:
    out = out / 100.0
```

This magic normalization handles percentage-as-integer inputs but could silently corrupt legitimate scores > 1.0 in other contexts. Same pattern in `claims_runtime.py`.

### N4. The `__all__` list in `__init__.py` has 350+ entries and is manually maintained

No automated check ensures it stays in sync with actual exports. Missing an entry means the symbol is importable but not in `__all__`, which affects `from context_framework import *`.

### N5. Test coverage is thin for core modules

- `test_manager.py`: 7 tests for a 644-line module
- `test_retrieval.py`: 2 tests
- `test_hybrid_retrieval.py`: 1 test
- `test_tri_provider_pipeline.py`: 4 tests (2 depend on external scripts)
- No dedicated test file for `scoring.py`, `tokenizer.py`, `summarization.py`, `quality.py`, or `providers.py`
- No tests for `provider_sdk.py`'s perplexity computation or speculative decoding metrics

### N6. All runtime tests follow the same pattern and could be parameterized

Each `test_*_runtime.py` file has nearly identical test structure: extract indicators, run dry mode, check idempotency, verify stats. These could be a single parameterized test suite.

---

## Good Patterns

1. **Immutable result types**: All report dataclasses use `frozen=True`, preventing accidental mutation of execution results.

2. **Idempotency-first design**: Every Commander runtime has first-class idempotency support with configurable TTL. This is a best practice for operational automation.

3. **Protocol-based dependency injection**: All external integrations (SIEM, EDR, IAM, etc.) use `Protocol` classes, making testing trivial with `NoOp*` and `InMemory*` implementations.

4. **Three-tier adapter pattern**: Every integration point has `Protocol` + `NoOp*` (for testing) + `InMemory*` (for local dev) + `HTTP*` (for production) + `build_*_from_env()` factory. This is well-structured.

5. **Retry with backoff**: The retry logic correctly handles transient failures with configurable backoff and idempotency integration.

6. **Thread-safe idempotency store**: `InMemoryIdempotencyStore` uses `threading.Lock` and TTL-based expiry with pruning.

7. **Audit logging**: Every tool execution is logged with full context (timestamps, latency, idempotency keys, truncated payloads).

8. **Clean data flow in `ContextManager`**: The build process (system -> pinned -> recent conversation -> ranked pool -> summary) is well-ordered with clear priority rules.

9. **`slots=True` on all dataclasses**: Consistent use of `__slots__` for memory efficiency and typo prevention.

10. **Defensive SDK extraction**: `_extract_openai_preview`, `_extract_anthropic_preview`, etc. handle both dict and object SDK responses gracefully.

---

## File-by-File Detail

### `models.py` (59 lines) -- CLEAN

- Well-structured core types
- Issues: M1 (no text validation), M2 (silent importance clamping), L2 (hardcoded system role)

### `manager.py` (644 lines) -- GOOD

- Core context management logic is solid
- Issues: H7 (binary search redundancy), H8 (unreachable guard), M11 (abstention gap), L1 (structlog dependency), L9 (clear doesn't reset tokens)

### `scoring.py` (74 lines) -- CLEAN

- Issues: H3 (unbounded cache), L3 (manual norm)

### `retrieval.py` (191 lines) -- CLEAN

- Issues: M3 (Chroma distance assumption), L4 (list vs tuple inconsistency)

### `tokenizer.py` (49 lines) -- CLEAN

- Issues: H6 (empty text returns 1)

### `summarization.py` (101 lines) -- CLEAN

- Issues: M5 (assert for runtime check), M12 (missing cross-field validation)

### `quality.py` (93 lines) -- CLEAN

- Issues: M4 (case-sensitive faithfulness)

### `providers.py` (134 lines) -- MINOR ISSUES

- Issues: H5 (dead cloud/native branch)

### `provider_sdk.py` (816 lines) -- GOOD, some complexity

- Well-structured multi-provider support
- Issues: L6 (no URL validation), L7 (undocumented property)

### `hybrid_retrieval.py` (211 lines) -- GOOD

- RRF fusion implementation is correct
- Issues: L5 (redundant corpus storage)

### `tri_provider_pipeline.py` (964 lines) -- GOOD but large

- Issues: M6 (client creation per call), N2 (domain-agnostic simulation)

### `tri_provider_use_cases.py` (557 lines) -- CRITICAL

- Issues: C1 (module-level side effect)

### `framework_bridges.py` (309 lines) -- GOOD

- Issues: M7 (asyncio.run nesting)

### `anthropic_agentic_text_system.py` (499 lines) -- GOOD

- Issues: L8 (None role handling)

### `live_integration_harness.py` (471 lines) -- GOOD

- Well-structured integration test harness with env-gated checks

### `soc_runtime.py` (875 lines) -- GOOD (first instance of runtime pattern)

- Issues: M8 (3-term query limit), M9 (broad substring matching), M10 (broad host regex)

### `aml_runtime.py` (1158 lines) -- DUPLICATED from soc_runtime pattern

- Issues: H1 (duplication), N3 (\_as_float magic normalization)

### `claims_runtime.py` (1145 lines) -- DUPLICATED, also redefines shared types

- Issues: H1 (duplication), H2 (redefines AuditLogger/IdempotencyStore)

### `supply_chain_runtime.py` (1217 lines) -- DUPLICATED

- Issues: H1 (duplication)

### `grid_outage_runtime.py` (1389 lines) -- DUPLICATED

### `pharmacovigilance_runtime.py` (1234 lines) -- DUPLICATED

### `manufacturing_runtime.py` (1430 lines) -- DUPLICATED

### `emergency_operations_runtime.py` (1516 lines) -- DUPLICATED

### `clinical_operations_runtime.py` (1434 lines) -- DUPLICATED

### `regulatory_change_runtime.py` (1617 lines) -- DUPLICATED

### `contract_negotiation_runtime.py` (1557 lines) -- DUPLICATED

### `legacy_modern_migration_runtime.py` (1503 lines) -- DUPLICATED

### `contact_center_autopilot_runtime.py` (1486 lines) -- DUPLICATED

All 12 runtime files share issues H1 (massive duplication). Each is 1,100-1,600 lines, of which approximately 400-500 lines are domain-specific and 600-1,000 lines are identical infrastructure boilerplate.

### `__init__.py` (747 lines) -- NEEDS RESTRUCTURING

- Issues: H4 (eager import of everything)

---

## Recommended Priority Actions

1. **Extract shared runtime infrastructure** (H1, H2) -- saves ~10,000 lines, prevents drift bugs
2. **Fix module-level validation** (C1) -- prevents import-time failures
3. **Add LRU bounds to EmbeddingScorer cache** (H3) -- prevents memory leak
4. **Lazy imports in `__init__.py`** (H4) -- improves import performance
5. **Remove dead branch in OllamaChatAdapter** (H5) -- eliminates confusion
6. **Fix empty text token count** (H6) -- prevents subtle budget miscalculation
7. **Add tests for core modules** (N5) -- scoring, tokenizer, summarization, quality have zero dedicated tests
