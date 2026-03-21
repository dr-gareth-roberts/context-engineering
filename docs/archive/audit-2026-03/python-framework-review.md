# Python Framework Audit Fix Review

**Date:** 2026-03-17
**Reviewer:** Claude Opus 4.6 (automated verification)
**Scope:** Verify all fixes from `python-framework-fixes.md` against the original `python-framework-audit.md`

---

## Overall Assessment

The fixes correctly address all targeted issues (C1, H1-H8, M3-M6, M12). The `runtime_base.py` extraction is well-designed. Three residual problems were found and fixed during this review (unused imports in refactored files, missing `__all__` entries).

---

## Issue-by-Issue Verification

### C1: `validate_use_case_catalog()` at import time -- FIXED

The bare call on the former line 557 of `tri_provider_use_cases.py` has been removed. The file now ends at line 555 with the function definition. The function remains available for explicit validation. Confirmed: importing `context_framework` no longer triggers validation.

### H1/H2: Shared runtime infrastructure -- FIXED (with minor residual)

**`runtime_base.py` is well-structured.** It correctly consolidates:

- `unique_preserve()` -- case-insensitive deduplication helper
- `AuditLogger` / `IdempotencyStore` protocols
- `NoOpAuditLogger`, `JSONLAuditLogger`, `InMemoryIdempotencyStore` implementations
- `HTTPJSONAdapterBase` with URL validation and error handling
- `ExecutionTask` / `ToolExecutionResult` frozen dataclasses
- `BaseCommanderMixin` with `_execute_tasks`, `_execute_task`, `_execute_with_retry`, `_is_retryable_error`, `_log_audit_event`, `_safe_payload`

**`soc_runtime.py`** correctly imports all shared symbols from `runtime_base` and uses `BaseCommanderMixin` as a parent class for `SOCIncidentCommander`. Domain-specific protocols (`SIEMAdapter`, `EDRAdapter`, `IAMAdapter`) and their implementations remain in place.

**`claims_runtime.py`** correctly imports from `runtime_base` and aliases `ToolExecutionResult as ClaimsToolExecutionResult` for backward compatibility. The `_log_audit_event` override (using `batch_id` instead of `incident_id`) is safe because the base mixin never calls `_log_audit_event` internally -- it is always invoked by the concrete `run()` method.

**Residual observations:**

- `aml_runtime.py` and `supply_chain_runtime.py` still import `AuditLogger`, `IdempotencyStore`, etc. from `soc_runtime` rather than `runtime_base`. This works at runtime (Python re-exports imported names), but creates an indirect dependency chain. Future work should update these to import from `runtime_base` directly.
- The remaining 11 runtime files still contain their own copies of `_HTTPJSONAdapterBase`, `_unique_preserve`, `_ExecutionTask`, and execution boilerplate. The fix summary acknowledges this as out-of-scope for this pass.

### H3: `EmbeddingScorer._cache` unbounded growth -- FIXED

`scoring.py` now uses `OrderedDict` with LRU eviction:

- Cache hits call `move_to_end()` to maintain LRU order
- After insertion, `popitem(last=False)` evicts the oldest entry when `len > max_cache_size`
- Default `max_cache_size=2048` is reasonable
- The `_DEFAULT_EMBEDDING_CACHE_SIZE` constant is a good touch for documentation

### H5: `OllamaChatAdapter.request()` dead branch -- FIXED

The two identical branches are now meaningfully different:

- Cloud mode (`use_cloud=True`): passes parameters like `temperature`, `top_p` as top-level keys (OpenAI-compatible)
- Native mode (`use_cloud=False`): extracts `temperature`, `top_p`, `top_k`, `num_predict`, `seed`, `stop` from `extra` and nests them under an `options` dict per Ollama's native `/api/chat` API spec
- The `extra.pop(key)` pattern correctly removes keys from `extra` before `payload.update(extra)`, preventing duplication

### H6: `ApproxTokenCounter.count()` returns 0 for empty -- FIXED

`tokenizer.py` line 28 now returns `0` instead of `self._min_tokens` for empty/whitespace-only text. The `min_tokens` parameter still applies to non-empty text.

### H7: Binary search token count redundancy -- FIXED

`manager.py` `_truncate_item()`:

- Now caches `token_count = self._token_counter.count(text)` before the binary search
- Uses the cached value for the "fits in budget" early return
- Tracks `best_tokens` alongside `best` in the binary search loop
- Returns `replace(item, text=best, token_count=best_tokens)` without re-counting

### H8: Unreachable `total_window <= 0` guard -- FIXED

`manager.py` `_recency_score()` now has only two cases:

1. `if newest <= oldest: return 1.0`
2. Direct computation: `age_position / total_window` (clamped to [0, 1])

The dead `if total_window <= 0` branch is removed.

### M3: ChromaRetriever distance metric -- FIXED

`retrieval.py` `ChromaRetriever` now accepts a `distance_metric: Literal["l2", "cosine", "ip"]` parameter (default `"l2"` for backward compatibility). The `_distance_to_score()` method handles each metric:

- L2: `1.0 / (1.0 + distance)` -- bounded (0, 1], better than the original `1.0 - distance` which could go negative
- Cosine: `1.0 - distance` -- correct for Chroma's cosine distance convention
- Inner product: `-distance` -- correct for Chroma's negative IP convention

### M4: Case/whitespace normalization in faithfulness judge -- FIXED

`quality.py` `QuoteOnlyFaithfulnessJudge.judge()` now:

- Converts both claim and context to lowercase via `.lower()`
- Collapses whitespace runs to single spaces via `_WHITESPACE_RUN_RE.sub(" ", ...)`
- Updated verdict reason to note case-insensitive matching

### M5: `assert` replaced with `RuntimeError` -- FIXED

`summarization.py` `_clip_to_budget()` line 88-89 now reads:

```python
if self.token_counter is None:
    raise RuntimeError("token_counter is not set; ensure __post_init__ has run")
```

This survives `python -O` (optimized mode).

### M6: SDK clients cached in `tri_provider_pipeline` -- FIXED

`tri_provider_pipeline.py` adds three `_*_client` fields (default `None`) to `TriProviderPipeline`. The `_run_live()` method checks each for `None` before creating a new client, then reuses the cached instance. The lazy import + cache pattern is correct.

### M12: Cross-field validation in `RollingSummaryConfig` -- FIXED

`summarization.py` `RollingSummaryConfig.validate()` now rejects `keep_recent_messages >= trigger_messages` with a descriptive `ValueError`. This prevents the silent no-op pruning behavior identified in the audit.

---

## Issues Found and Fixed During This Review

### R1: Unused imports in `soc_runtime.py` (post-refactor)

After extracting shared code to `runtime_base.py`, `soc_runtime.py` retained `import time` and `Callable` in the typing import even though neither is used anywhere in the file after the refactoring (execution logic that used `time.perf_counter()` and `Callable` for task types now lives in `runtime_base.py`).

**Fixed:** Removed `import time` and `Callable` from the import list.

### R2: Unused imports in `claims_runtime.py` (post-refactor)

Similarly, `claims_runtime.py` retained `import time`, `import json`, and `Callable` -- none of which are used after the refactoring.

**Fixed:** Removed `import time`, `import json`, and `Callable` from the import list.

### R3: Missing `__all__` entries in `__init__.py`

Several symbols imported by `__init__.py` were absent from the `__all__` list:

- `HybridInMemoryRetriever` (imported from `hybrid_retrieval`)
- `FaithfulnessJudge`, `FaithfulnessVerdict`, `QuoteOnlyFaithfulnessJudge` (imported from `quality`)
- `average_precision`, `mrr`, `ndcg_at_k`, `precision_at_k`, `recall_at_k` (imported from `quality`)
- `cosine_similarity` (from `scoring`, was not imported at all)

**Fixed:** Added `cosine_similarity` to the import statement and all missing symbols to `__all__`.

---

## Remaining Observations (not blocking)

1. **Implicit re-exports:** `aml_runtime.py` and `supply_chain_runtime.py` import `AuditLogger` etc. from `soc_runtime` rather than `runtime_base`. This works at runtime but may cause Pyright `reportPrivateImportUsage` warnings since `soc_runtime` doesn't explicitly re-export them via `__all__`. The fix summary notes the other 11 runtimes are out-of-scope for this pass.

2. **`soc_runtime.py` retains `json` import:** This is used by `InMemorySIEMAdapter.query()` (line 80: `json.dumps(event, ...)`), so it is a legitimate dependency.

3. **`_log_audit_event` signature asymmetry:** The base mixin defines `_log_audit_event(*, incident_id, mode, row)` while `CatastropheClaimsCommander` overrides it with `_log_audit_event(*, batch_id, mode, row)`. This works because the mixin never calls `_log_audit_event` internally -- each concrete `run()` method calls it directly. However, this means the base mixin's `_log_audit_event` is dead code in any class that overrides it. A cleaner design might make the identifier field name configurable, but this is not a functional issue.

4. **H4 (lazy imports in `__init__.py`) not addressed:** The audit identified eager importing of all runtime modules as a performance concern. The fix summary acknowledges this is deferred work.

---

## Files Modified During This Review

| File                                         | Change                                                                                                                                                                                                                                                  |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `python/context_framework/soc_runtime.py`    | Removed unused `import time` and `Callable`                                                                                                                                                                                                             |
| `python/context_framework/claims_runtime.py` | Removed unused `import time`, `import json`, and `Callable`                                                                                                                                                                                             |
| `python/context_framework/__init__.py`       | Added `cosine_similarity` import; added `HybridInMemoryRetriever`, `FaithfulnessJudge`, `FaithfulnessVerdict`, `QuoteOnlyFaithfulnessJudge`, `average_precision`, `cosine_similarity`, `mrr`, `ndcg_at_k`, `precision_at_k`, `recall_at_k` to `__all__` |

---

## Test Verification

Tests could not be run during this review (sandbox restriction). The changes made here (removing unused imports, adding `__all__` entries) are low-risk and should not affect test outcomes. The `test_manager.py` tests cover the core `ContextManager` behavior including budget enforcement, pinned memory prioritization, query relevance, conversation recency, rolling summaries, and abstention logic.

---

## Verdict

All 13 targeted fixes are correctly implemented. Three residual cleanup issues (R1, R2, R3) were found and fixed. The `runtime_base.py` extraction is solid and provides a clean template for migrating the remaining 11 runtime files.
