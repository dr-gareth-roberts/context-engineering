# Architecture

## Design Principles

### 1. Zero external dependencies (beyond ce-core)

Every package depends only on `ce-core`. This means:

- No version conflicts between packages
- Install only what you need
- Predictable dependency tree

### 2. Duck-typing over hard dependencies

Packages that interface with external systems (SDKs, frameworks, vector stores, LLM providers) use duck-typed interfaces rather than importing the external library. `ce-frameworks` doesn't import LangChain — it matches the `LangChainLike` interface. `ce-council` doesn't import any provider SDK — it accepts anything with a `generate()` method.

### 3. Sync by default, async when needed

The `MaybeAsync` pattern lets the same code path work synchronously (zero Promise overhead) or asynchronously (when embeddings or LLM calls are involved). `pack()` is sync; `packAsync()` is async. `build()` is sync; `buildAsync()` is async. They share the same implementation via `chain()`.

### 4. Composable, not monolithic

Features compose through standard `ContextItem[]` → `ContextPack` interfaces. The output of any operation is valid input to the next. Pipeline, compiler, and council all ultimately call `pack()` from ce-core.

### 5. Cross-language parity

Every TypeScript package has a Python equivalent with the same API surface (snake_case). Shared JSON Schemas in `schemas/` ensure cross-language validation consistency.

## Data Flow

```
Items → [Score] → [Sort] → [Select] → [Place] → [Format] → API Call
         ↑          ↑         ↑          ↑          ↑
      Scorer    Budget    Allocator  Attention   Template
      (custom   (token    (kind-    (model     (Anthropic/
       weights)  limit)    aware)    profile)   OpenAI)
```

Every stage is optional. The minimal path is `Items → Select → API Call`.

## Package Categories

### Core Layer

`ce-core` contains all algorithms with zero runtime dependencies (only Zod for validation). Everything else builds on this.

**Key modules**: pack.ts, score.ts, pipeline.ts, placement.ts, quality.ts, cost.ts, allocation.ts, cache-topology.ts, session.ts, beads.ts, relevance.ts, redundancy.ts, bm25.ts, compaction.ts, stream.ts, diff.ts, template.ts

### Infrastructure Layer

- `ce-providers`: Connects to real LLM APIs (OpenAI, Anthropic). Lazy-loaded clients.
- `ce-memory`: Persistent storage with consistent TTL semantics across 4 backends.
- `ce-cli`: User-facing CLI wrapping ce-core operations.

### Orchestration Layer

- `ce-council`: Multi-model deliberation — manages context windows for each participant.
- `ce-entangle`: Multi-agent mesh — shares context items across agents during pack().
- `ce-router`: Routes to cheapest model by analysing context complexity.

### Quality Layer

- `ce-adversarial`: Proactive testing — injects attacks to find vulnerabilities.
- `ce-immune`: Reactive learning — builds antibodies from past failures.
- `ce-debugger`: Diagnostic — traces bad outputs back to context problems.
- `ce-drift`: Monitoring — detects quality degradation over time.

### Optimisation Layer

- `ce-compiler`: Declarative — specify what you want, compiler optimises for the target model.
- `ce-adaptive`: Learning — adjusts scoring weights from outcome feedback.
- `ce-time-travel`: Debugging — branch/merge context states to compare approaches.

### Integration Layer

- `ce-sdk-interceptors`: Wraps existing OpenAI/Anthropic SDK calls with automatic context management.
- `ce-frameworks`: Middleware for LangChain, LlamaIndex, CrewAI via duck-typed Proxies.
- `ce-rag`: Information-gain retrieval that considers existing context.

## Python Architecture

The Python SDK mirrors the TypeScript structure:

```
python/
  context_engineering/     # Core SDK — mirrors all TS packages
    core.py               # pack, diff, estimate_tokens, etc.
    pipeline.py           # create_pipeline()
    council.py            # create_council()
    adversarial.py        # create_adversarial_tester()
    compiler.py           # context_program(), create_context_compiler()
    drift.py              # create_drift_monitor()
    immune.py             # create_immune_system()
    entangle.py           # create_entanglement_mesh()
    time_travel.py        # create_timeline()
    ...
  context_framework/       # Domain runtimes (lazy-loaded)
    aml_runtime.py
    claims_runtime.py
    ...12 domain-specific runtimes
```

`context_framework` uses `__getattr__`-based lazy imports — domain runtimes are only loaded when accessed, keeping import time fast.

## Test Architecture

- TypeScript: Vitest, ~1,264 tests across 17 packages
- Python: pytest, ~908 tests
- CI: Matrix testing across Node 18/20/22 and Python 3.10/3.11/3.12
- Pre-commit: Husky + lint-staged (Prettier, ESLint, ruff)
