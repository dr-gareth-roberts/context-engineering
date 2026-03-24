# Package Overview

The toolkit is organised into 17 packages across 5 categories. All packages depend only on `ce-core` (no inter-package dependencies beyond that). Every TypeScript package has full Python parity.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your Application                         │
├─────────────────────────────────────────────────────────────────┤
│  Integration Layer                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ sdk-         │ │ frameworks   │ │ rag          │            │
│  │ interceptors │ │ (LangChain,  │ │ (info-gain   │            │
│  │ (OpenAI,     │ │  LlamaIndex, │ │  retrieval)  │            │
│  │  Anthropic)  │ │  CrewAI)     │ │              │            │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘            │
├─────────┼────────────────┼────────────────┼─────────────────────┤
│  Multi-Model & Multi-Agent                                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ council      │ │ entangle     │ │ router       │            │
│  │ (deliberate) │ │ (mesh)       │ │ (complexity) │            │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘            │
├─────────┼────────────────┼────────────────┼─────────────────────┤
│  Quality & Safety                                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────┐│
│  │ adversarial  │ │ immune       │ │ drift        │ │debugger││
│  │ (red-team)   │ │ (antibodies) │ │ (monitor)    │ │(diag.) ││
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └───┬────┘│
├─────────┼────────────────┼────────────────┼──────────────┼──────┤
│  Optimisation                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ compiler     │ │ adaptive     │ │ time-travel  │            │
│  │ (declarative)│ │ (feedback)   │ │ (branching)  │            │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘            │
├─────────┴────────────────┴────────────────┴─────────────────────┤
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                      ce-core                              │   │
│  │  pack · score · diff · place · quality · cost · cache     │   │
│  │  allocation · session · pipeline · BEADS · compaction     │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│  ┌──────────────┐ ┌────────┴──────┐ ┌──────────────┐           │
│  │ providers    │ │ memory        │ │ cli          │           │
│  │ (OpenAI,     │ │ (InMemory,    │ │ (11 commands)│           │
│  │  Anthropic)  │ │  File, SQLite,│ │              │           │
│  │              │ │  Redis)       │ │              │           │
│  └──────────────┘ └───────────────┘ └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

## Package Details

### Core (stable, published to npm/PyPI)

| Package          | npm                              | Description         | Key exports                                                                                                   |
| ---------------- | -------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------- |
| **ce-core**      | `@context-engineering/core`      | All core algorithms | `pack`, `pipeline`, `diff`, `estimateTokens`, `placeItems`, `analyzeContext`, `estimateCost`, `createHandoff` |
| **ce-providers** | `@context-engineering/providers` | LLM adapters        | `OpenAIProvider`, `AnthropicProvider`, `openaiTokenEstimator`, `presets`                                      |
| **ce-memory**    | `@context-engineering/memory`    | Persistence         | `createMemoryStore`, `InMemoryStore`, `FileStore`, `SqliteStore`, `RedisStore`                                |
| **ce-cli**       | `@context-engineering/cli`       | Command line        | `ce pack`, `ce trace`, `ce diff`, `ce cost`, `ce handoff`, `ce quality`, ...                                  |

### Multi-Model & Multi-Agent

| Package         | npm                             | Description                                             | Key exports                                                        |
| --------------- | ------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------ |
| **ce-council**  | `@context-engineering/council`  | Multiple LLM experts debate and synthesise answers      | `createCouncil`, `ROLE_PRESETS`, `computeConvergence`              |
| **ce-entangle** | `@context-engineering/entangle` | Agents share context through a scoped pub/sub mesh      | `createEntanglementMesh`, `AgentHandle`                            |
| **ce-router**   | `@context-engineering/router`   | Route to cheapest model by analysing context complexity | `createContextRouter`, `createAdaptiveRouter`, `analyzeComplexity` |

### Quality & Safety

| Package            | npm                                | Description                              | Key exports                                |
| ------------------ | ---------------------------------- | ---------------------------------------- | ------------------------------------------ |
| **ce-adversarial** | `@context-engineering/adversarial` | Red-team with 6 attack types             | `createAdversarialTester`, `applyAttack`   |
| **ce-immune**      | `@context-engineering/immune`      | Learn from failures, screen future packs | `createImmuneSystem`, `extractFingerprint` |
| **ce-debugger**    | `@context-engineering/debugger`    | Diagnose bad outputs                     | `createContextDebugger`                    |
| **ce-drift**       | `@context-engineering/drift`       | Monitor quality degradation              | `createDriftMonitor`                       |

### Optimisation

| Package            | npm                                | Description                             | Key exports                               |
| ------------------ | ---------------------------------- | --------------------------------------- | ----------------------------------------- |
| **ce-compiler**    | `@context-engineering/compiler`    | Declarative context to optimised layout | `contextProgram`, `createContextCompiler` |
| **ce-adaptive**    | `@context-engineering/adaptive`    | Learn scoring weights from outcomes     | `createContextOptimizer`                  |
| **ce-time-travel** | `@context-engineering/time-travel` | Branch/merge context states             | `createTimeline`                          |

### Integration

| Package                 | npm                                     | Description                | Key exports                                                          |
| ----------------------- | --------------------------------------- | -------------------------- | -------------------------------------------------------------------- |
| **ce-sdk-interceptors** | `@context-engineering/sdk-interceptors` | Drop-in SDK wrappers       | `withContext`, `withContextAnthropic`                                |
| **ce-frameworks**       | `@context-engineering/frameworks`       | Framework middleware       | `withContextLangChain`, `withContextLlamaIndex`, `withContextCrewAI` |
| **ce-rag**              | `@context-engineering/rag`              | Information-gain retrieval | `createContextAwareRetriever`, `createHybridRetriever`               |

## Dependency Graph

All packages depend on `ce-core`. Two also depend on `ce-providers`:

```
ce-core ← ce-providers ← ce-sdk-interceptors
                        ← ce-cli
       ← ce-memory
       ← ce-adaptive
       ← ce-frameworks
       ← ce-debugger
       ← ce-rag
       ← ce-router
       ← ce-council
       ← ce-adversarial
       ← ce-time-travel
       ← ce-drift
       ← ce-immune
       ← ce-compiler
       ← ce-entangle
```

## Python Parity

Every TypeScript package has a corresponding Python module in `context_engineering/`:

| TypeScript       | Python module                     |
| ---------------- | --------------------------------- |
| `ce-core`        | `context_engineering.core`        |
| `ce-council`     | `context_engineering.council`     |
| `ce-adversarial` | `context_engineering.adversarial` |
| `ce-time-travel` | `context_engineering.time_travel` |
| `ce-drift`       | `context_engineering.drift`       |
| `ce-immune`      | `context_engineering.immune`      |
| `ce-compiler`    | `context_engineering.compiler`    |
| `ce-entangle`    | `context_engineering.entangle`    |
| ...              | ...                               |

All modules are accessible via `from context_engineering import ...`.
