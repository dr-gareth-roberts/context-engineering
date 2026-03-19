# Audit Future Work — Implementation Plans (ALL COMPLETED)

> Generated from deep codebase audit (2026-03-19). All 6 workstreams were executed
> and merged to main on 2026-03-19. This document is retained for historical reference.
>
> **Status: ALL DONE** — 43 files changed, +2,154 / -3,505 lines, 1,282 tests passing.

---

## Priority 1 (HIGH): Python Runtime Deduplication (~1,925 lines) — DONE

**Problem:** 11 of 13 Python runtime files copy-paste identical infrastructure (~175 lines each):
`_unique_preserve()`, `_HTTPJSONAdapterBase`, `_ExecutionTask`, `_execute_tasks()`,
`_execute_task()`, `_execute_with_retry()`, `_is_retryable_error()`, `_log_audit_event()`,
`_safe_payload()`. Only `soc_runtime.py` and `claims_runtime.py` use `BaseCommanderMixin`.

**Approach:** Create a new `BaseIntegrationCommanderMixin` with the 3-field pattern
(`integration`, `operation`, `target`) used by the 11 runtimes, alongside the existing
2-field pattern (`tool`, `target`) used by SOC/Claims.

### Steps

1. **Add unified types to `runtime_base.py`**
   - Add `IntegrationActionResult` dataclass (frozen, slots)
   - Add `IntegrationExecutionTask` dataclass (frozen, slots)
   - Add `"429"` to `_is_retryable_error` markers (missing from base)
   - Add `BaseIntegrationCommanderMixin` with integration-specific execution methods
   - Export new types from `__init__.py`
   - **Test:** `python -m pytest tests/test_soc_runtime.py tests/test_claims_runtime.py`

2. **Pilot migration: `supply_chain_runtime.py`**
   - Inherit `BaseIntegrationCommanderMixin`, add type alias for backward compat
   - Remove all 9 duplicated functions, update imports from `soc_runtime` to `runtime_base`
   - **Test:** `python -m pytest tests/test_supply_chain_runtime.py`

3. **Migrate remaining 10 runtimes** (parallelizable in batches of 3-4)
   - Each: inherit mixin, add type alias, remove duplicates, update imports
   - AML last (most divergent result type)
   - **Test after each:** corresponding `test_*_runtime.py`

4. **Final cleanup**
   - Remove re-exports from `soc_runtime.py`, update `__init__.py`
   - **Test:** Full `python -m pytest`

**Estimated reduction:** ~1,925 to ~200 lines of shared infrastructure code.

---

## Priority 2 (HIGH): Fix TS/Python Schema Drift (10+ missing fields) — DONE

**Problem:** 10 TypeScript type fields missing that exist in JSON Schema + Python.
`ContextPlan` type entirely absent from TS.

### Steps

1. **Add 5 fields to `ContextItem` in `types.ts`**
   - `supersedes?: string`, `parentId?: string`, `cost?: number`, `latency?: number`, `links?: string[]`
   - All optional, purely additive
   - **Test:** `cd packages/ce-core && npx vitest run`

2. **Add same fields to `ContextItemSchema` in `schemas.ts`**
   - Fix `tokens` to use `.int()` (JSON Schema says "integer")
   - **Test:** `npx vitest run src/schemas.test.ts`

3. **Add `notes?: string[]` to `ContextPack` in `types.ts`**

4. **Add `ContextPlan` type and `ContextPlanSchema`**
   - Interface + Zod schema, export from `index.ts`

5. **Add 4 fields to `MemoryItem` in `ce-memory/src/types.ts`**
   - `lastAccessedAt?: string`, `isSummary?: boolean`, `embedding?: number[]`, `links?: string[]`
   - Update SqliteStore/FileStore to handle new fields
   - **Test:** `cd packages/ce-memory && npx vitest run`

6. **Verify `ce lint` accepts items with new fields**

---

## Priority 3 (MEDIUM): TS Sync/Async Deduplication (~1,000 lines) — DONE

**Problem:** `allocation.ts`, `cache-topology.ts`, `compaction.ts`, `pipeline.ts` have
near-verbatim sync/async copies differing only by `pack()` vs `await packAsync()`.

**Approach:** Higher-order function with `MaybeAsync<T>` utility.

### Steps

1. **Create `maybe-async.ts` utility (~15 lines)**
   - `MaybeAsync<T>` type, `chain()`, `all()` functions
   - Sync path never creates Promises (zero overhead)
   - **Test:** Unit tests for chain/all

2. **Refactor `allocation.ts`**
   - Extract shared logic into `packWithAllocationImpl(items, budget, allocations, options, packFn)`
   - Public functions become thin wrappers
   - **Test:** `npx vitest run src/allocation.test.ts`

3. **Refactor `cache-topology.ts`** (only 2 pack call sites differ)

4. **Refactor `compaction.ts`** (harder: async has summarizer batching)

5. **Refactor `pipeline.ts`** (consolidate build/buildAsync)

**Estimated reduction:** ~1,000 to ~500 lines plus ~15 line utility.

---

## Priority 4 (MEDIUM): Redis TTL Semantic Unification — DONE

**Problem:** RedisStore uses native `EX` expiry while other stores check TTL at query time.
This breaks `query({includeExpired: true})` and `get()` for expired items.

**Approach:** Remove Redis EX, manage TTL in application code.

### Steps

1. **Remove `EX` from RedisStore `put()`** — always `pipeline.set(key, data)` without TTL
2. **Check `pipeline.exec()` results** — throw on partial failure
3. **Add `closed` flag to all 4 stores** — throw on use-after-close
4. **Add TTL behavior tests** — verify expired items with `includeExpired: true`

---

## Priority 5 (MEDIUM): Add Critical Test Coverage — DONE

### Batch 1 — Pure logic, zero risk (parallelizable)

| Area                   | New/Modified File            | Tests                                         |
| ---------------------- | ---------------------------- | --------------------------------------------- |
| `hash.ts`              | `hash.test.ts` (new)         | 8: determinism, collision resistance, unicode |
| `runtime_base.py`      | `test_runtime_base.py` (new) | 20: retry, idempotency, audit, HTTP adapter   |
| Pipeline quality gate  | `pipeline.test.ts` (add)     | 5: drop-until-threshold loop                  |
| Session custom options | `session.test.ts` (add)      | 3: compile with custom PackOptions            |

### Batch 2 — Python coverage (parallelizable)

| Area                      | New/Modified File                     | Tests                                   |
| ------------------------- | ------------------------------------- | --------------------------------------- |
| `AgentContextManager`     | `test_agent_context_manager.py` (new) | 18: budget, memory, handoff, abstention |
| `scoring.py`              | `test_scoring.py` (new)               | 10: keyword, embedding, cosine          |
| `tokenizer.py`            | `test_tokenizer.py` (new)             | 7: approx, tiktoken, empty string       |
| Async allocation/topology | existing test files (add)             | 8: async variants                       |

### Batch 3 — Web (requires setup)

| Area       | New File              | Tests                                    |
| ---------- | --------------------- | ---------------------------------------- |
| Web client | Multiple `*.test.tsx` | 15+: component rendering, hooks, parsing |
| Web server | `index.test.ts` (new) | 8: health, rate limit, CORS, proxy       |

**Total new tests:** ~100+

---

## Priority 6 (LOW-MEDIUM): Fix Remaining Bugs — DONE

### Batch 1 — Zero risk (parallel)

| Bug                                    | Fix                                       |
| -------------------------------------- | ----------------------------------------- |
| TiktokenCounter empty string returns 1 | Add `if not text.strip(): return 0` guard |
| `adaptEmbeddingProvider` dead code     | Add tests or remove entirely              |

### Batch 2 — Low risk (parallel)

| Bug                              | Fix                                                  |
| -------------------------------- | ---------------------------------------------------- |
| BM25 duplicate ID corrupts index | Check existing ID, remove old stats before re-adding |
| Ollama kwargs mutation           | Use dict comprehension instead of `extra.pop()`      |
| Summarizer swallows all errors   | Add optional `onError` callback, log errors          |

### Batch 3 — Medium risk

| Bug                                | Fix                                                                  |
| ---------------------------------- | -------------------------------------------------------------------- |
| FileStore close() no state cleanup | Add `closed` flag, clear items/loadPromise, throw on use-after-close |

---

## Execution Dependencies

All 6 priority workstreams are independent and can be executed in parallel.
Within each priority, steps are ordered sequentially.
