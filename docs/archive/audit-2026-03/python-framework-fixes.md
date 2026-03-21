# Python Framework Audit Fixes

**Date:** 2026-03-17
**Scope:** All Critical and High issues, plus practical Medium issues from the audit.

---

## Summary of Changes

| Severity | Issue                                                | Fix                                                                                                                            | Files Changed                                                                 |
| -------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| CRITICAL | C1: `validate_use_case_catalog()` at import time     | Removed module-level call; function remains available for explicit use                                                         | `tri_provider_use_cases.py`                                                   |
| HIGH     | H1/H2: ~10,000 lines duplicated across 12+ runtimes  | Extracted shared infrastructure into new `runtime_base.py`; updated `soc_runtime.py` and `claims_runtime.py` to import from it | `runtime_base.py` (new), `soc_runtime.py`, `claims_runtime.py`, `__init__.py` |
| HIGH     | H3: `EmbeddingScorer._cache` unbounded growth        | Replaced `dict` with `OrderedDict` LRU cache bounded to `max_cache_size` (default 2048)                                        | `scoring.py`                                                                  |
| HIGH     | H5: `OllamaChatAdapter.request()` dead branch        | Cloud and native branches now differ: native mode moves `temperature`/`top_p`/etc. into `options` dict per Ollama API spec     | `providers.py`                                                                |
| HIGH     | H6: `ApproxTokenCounter.count()` returns 1 for empty | Now returns 0 for empty/whitespace-only text                                                                                   | `tokenizer.py`                                                                |
| HIGH     | H7: Binary search token count redundancy             | Eliminated redundant `token_counter.count()` call after binary search loop by tracking `best_tokens` inline                    | `manager.py`                                                                  |
| HIGH     | H8: Unreachable `total_window <= 0` guard            | Removed dead branch in `_recency_score`                                                                                        | `manager.py`                                                                  |
| MEDIUM   | M3: ChromaRetriever assumes L2 distance              | Added `distance_metric` parameter (`"l2"`, `"cosine"`, `"ip"`) with correct score conversions                                  | `retrieval.py`                                                                |
| MEDIUM   | M4: Case-sensitive faithfulness matching             | `QuoteOnlyFaithfulnessJudge` now normalizes case and whitespace before comparison                                              | `quality.py`                                                                  |
| MEDIUM   | M5: `assert` for runtime invariant                   | Replaced `assert self.token_counter is not None` with proper `RuntimeError`                                                    | `summarization.py`                                                            |
| MEDIUM   | M6: Fresh SDK clients per live call                  | `TriProviderPipeline` now caches OpenAI/Anthropic/Cerebras clients across calls                                                | `tri_provider_pipeline.py`                                                    |
| MEDIUM   | M12: Missing cross-field validation                  | `RollingSummaryConfig.validate()` now rejects `keep_recent_messages >= trigger_messages`                                       | `summarization.py`                                                            |

---

## Detailed Changes

### C1: Remove module-level `validate_use_case_catalog()` (CRITICAL)

**File:** `python/context_framework/tri_provider_use_cases.py`

Removed the bare call `validate_use_case_catalog()` on line 557 that executed at import time. The function itself is unchanged and remains available for explicit validation.

### H1/H2: Extract shared runtime infrastructure (HIGH)

**New file:** `python/context_framework/runtime_base.py`

Created a centralized module containing:

- `unique_preserve()` -- deduplicate-preserving-order helper
- `AuditLogger` protocol
- `IdempotencyStore` protocol
- `NoOpAuditLogger` implementation
- `JSONLAuditLogger` implementation
- `InMemoryIdempotencyStore` implementation (thread-safe with TTL)
- `HTTPJSONAdapterBase` -- shared HTTP adapter with `_post()`
- `ExecutionTask` dataclass
- `ToolExecutionResult` dataclass
- `BaseCommanderMixin` -- mixin providing `_execute_tasks`, `_execute_task`, `_execute_with_retry`, `_is_retryable_error`, `_log_audit_event`, and `_safe_payload`

**File:** `python/context_framework/soc_runtime.py`

- Removed local definitions of `AuditLogger`, `IdempotencyStore`, `NoOpAuditLogger`, `JSONLAuditLogger`, `InMemoryIdempotencyStore`, `_HTTPJSONAdapterBase`, `ToolExecutionResult`, `_ExecutionTask`.
- All now imported from `runtime_base`.
- `SOCIncidentCommander` now inherits from `BaseCommanderMixin`, eliminating ~150 lines of duplicated methods (`_execute_tasks`, `_execute_task`, `_execute_with_retry`, `_is_retryable_error`, `_log_audit_event`, `_safe_payload`).
- Domain-specific protocols (`SIEMAdapter`, `EDRAdapter`, `IAMAdapter`) and implementations remain in place.

**File:** `python/context_framework/claims_runtime.py`

- Removed independently-defined `AuditLogger`, `IdempotencyStore`, `NoOpAuditLogger`, `JSONLAuditLogger`, `InMemoryIdempotencyStore` (were duplicates of the ones in `soc_runtime`, now unified via `runtime_base`).
- Removed local `_HTTPJSONAdapterBase`, `ClaimsToolExecutionResult`, `_ExecutionTask`.
- `CatastropheClaimsCommander` now inherits from `BaseCommanderMixin`.
- `_log_audit_event` kept as local override (uses `batch_id` instead of `incident_id`).
- `ClaimsToolExecutionResult` is now an alias for `runtime_base.ToolExecutionResult`.

**File:** `python/context_framework/__init__.py`

- Added imports from `runtime_base` for `AuditLogger`, `BaseCommanderMixin`, `ExecutionTask`, `HTTPJSONAdapterBase`, `unique_preserve`.
- Updated `soc_runtime` import block to no longer import `AuditLogger`, `IdempotencyStore`, etc. (they come from `runtime_base` now).
- Added new symbols to `__all__`.

### H3: Bounded `EmbeddingScorer` cache (HIGH)

**File:** `python/context_framework/scoring.py`

- Changed `_cache` from `dict` to `collections.OrderedDict`.
- Added `max_cache_size: int = 2048` parameter.
- `_embed_cached()` now calls `move_to_end()` on cache hits and `popitem(last=False)` when the cache exceeds the size limit (LRU eviction).

### H5: `OllamaChatAdapter.request()` dead branch (HIGH)

**File:** `python/context_framework/providers.py`

- Merged the two identical branches into a single payload construction.
- When `use_cloud=False` (native Ollama), parameters like `temperature`, `top_p`, `top_k`, `num_predict`, `seed`, `stop` are extracted from `extra` and placed into an `options` dict, matching Ollama's native `/api/chat` API format.

### H6: `ApproxTokenCounter.count()` empty text (HIGH)

**File:** `python/context_framework/tokenizer.py`

- Changed `return self._min_tokens` to `return 0` for empty/whitespace-only text.

### H7: Binary search redundancy (HIGH)

**File:** `python/context_framework/manager.py`

- `_truncate_item()` no longer calls `token_counter.count(text)` twice for the fits-in-budget case (cached in `token_count` variable).
- The binary search loop now tracks `best_tokens` alongside `best`, eliminating the redundant re-count after the loop.

### H8: Unreachable guard in `_recency_score` (HIGH)

**File:** `python/context_framework/manager.py`

- Removed `if total_window <= 0: return 1.0` since this is unreachable when `newest > oldest` (already guarded by the first check).

### M3: ChromaRetriever distance metric (MEDIUM)

**File:** `python/context_framework/retrieval.py`

- Added `distance_metric: Literal["l2", "cosine", "ip"]` parameter (default `"l2"` for backward compatibility).
- New `_distance_to_score()` method handles each metric correctly:
  - L2: `1.0 / (1.0 + distance)` (bounded 0-1)
  - Cosine: `1.0 - distance`
  - Inner product: `-distance`

### M4: Case-sensitive faithfulness matching (MEDIUM)

**File:** `python/context_framework/quality.py`

- `QuoteOnlyFaithfulnessJudge.judge()` now normalizes both claim and context to lowercase and collapses whitespace runs before substring comparison.
- Updated the "pass" verdict reason to note case-insensitive matching.

### M5: `assert` for runtime invariant (MEDIUM)

**File:** `python/context_framework/summarization.py`

- Replaced `assert self.token_counter is not None` with `if self.token_counter is None: raise RuntimeError(...)`.

### M6: Fresh SDK clients per call (MEDIUM)

**File:** `python/context_framework/tri_provider_pipeline.py`

- Added `_openai_client`, `_anthropic_client`, `_cerebras_client` fields (default `None`).
- `_run_live()` now creates clients only on first use and reuses them for subsequent calls.

### M12: Missing cross-field validation (MEDIUM)

**File:** `python/context_framework/summarization.py`

- `RollingSummaryConfig.validate()` now raises `ValueError` if `keep_recent_messages >= trigger_messages`, since this configuration would prevent the rolling summary from ever pruning.

---

## Files Changed

| File                                                 | Action                                                    |
| ---------------------------------------------------- | --------------------------------------------------------- |
| `python/context_framework/runtime_base.py`           | **Created** -- shared runtime infrastructure              |
| `python/context_framework/tri_provider_use_cases.py` | Removed import-time validation call                       |
| `python/context_framework/tokenizer.py`              | Fixed empty text token count                              |
| `python/context_framework/scoring.py`                | Added LRU cache eviction                                  |
| `python/context_framework/providers.py`              | Fixed dead branch, added native Ollama options            |
| `python/context_framework/manager.py`                | Fixed binary search redundancy, removed dead guard        |
| `python/context_framework/summarization.py`          | Fixed assert, added cross-field validation                |
| `python/context_framework/retrieval.py`              | Added distance_metric parameter                           |
| `python/context_framework/quality.py`                | Added case/whitespace normalization                       |
| `python/context_framework/soc_runtime.py`            | Refactored to use runtime_base                            |
| `python/context_framework/claims_runtime.py`         | Refactored to use runtime_base, removed duplicate classes |
| `python/context_framework/tri_provider_pipeline.py`  | Added client caching                                      |
| `python/context_framework/__init__.py`               | Updated imports for runtime_base                          |

---

## Remaining Work (not addressed in this pass)

The remaining 11 runtime files (`aml_runtime.py`, `supply_chain_runtime.py`, `grid_outage_runtime.py`, `pharmacovigilance_runtime.py`, `manufacturing_runtime.py`, `emergency_operations_runtime.py`, `clinical_operations_runtime.py`, `regulatory_change_runtime.py`, `contract_negotiation_runtime.py`, `legacy_modern_migration_runtime.py`, `contact_center_autopilot_runtime.py`) still contain their own copies of `_HTTPJSONAdapterBase`, `_unique_preserve`, `_ExecutionTask`, and the boilerplate execution methods. These should be updated to import from `runtime_base` following the same pattern demonstrated in `soc_runtime.py` and `claims_runtime.py`. The `runtime_base.py` module and the two refactored runtimes serve as the template.

The `__init__.py` would benefit from lazy imports (`__getattr__` pattern) to avoid loading all runtime modules at import time.
