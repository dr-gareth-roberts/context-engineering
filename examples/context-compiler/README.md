# Context Compiler — Declarative Context Compilation

Demonstrates how to declare a context program with named slots, constraints, and per-model optimisation targets instead of manually arranging items.

## What it demonstrates

A code-review assistant scenario where the compiler manages context layout:

1. **Program declaration:** 5 named slots (system, code, docs, history, extra) with position constraints (`first`, `last`), per-slot token budgets, and selection strategies (priority, recency, relevance).
2. **Multi-model compilation:** The same items compiled for Claude (primacy/recency attention bias) and GPT-5.4 (uniform attention with logical grouping), showing how item ordering differs.
3. **Constraint enforcement:** Coverage, budget-utilisation, and freshness constraints with diagnostic messages when violated.
4. **Tight budget behaviour:** With only 300 tokens, the compiler prioritises required slots and reports what was dropped.
5. **Error diagnostics:** Missing a required slot (system prompt) produces actionable error diagnostics.

## Packages used

- `@context-engineering/core` — `ContextItem` type definitions
- `@context-engineering/compiler` — `createContextCompiler`, `contextProgram`, slot/constraint types

## Running

```bash
# From the repository root
pnpm install
pnpm run build:packages
npx tsx examples/context-compiler/index.ts
```

## Output

The script prints a narrative showing slot breakdowns, quality metrics, model-specific optimisation passes, and diagnostic messages. No external APIs are called — everything runs locally with simulated code-review data.
