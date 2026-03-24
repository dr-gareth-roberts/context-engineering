# @context-engineering/compiler

Declarative context compiler — define what your context should contain with slots and constraints, and the compiler optimises the layout for a target model.

## How It Works

Instead of manually sorting and slicing context items, you declare a **program**: named slots (e.g., "system", "code", "history") with per-slot strategies and budgets, plus constraints (no contradictions, minimum coverage). The compiler fills slots, runs optimisation passes tuned for your target model's attention pattern, and returns diagnostics when constraints are violated.

## Quick Start

```typescript
import {
  contextProgram,
  createContextCompiler,
} from "@context-engineering/compiler";

const program = contextProgram()
  .declare("system", { kind: "system", required: true, position: "first" })
  .declare("code", { kind: "code", strategy: "relevance", deduplicate: true })
  .declare("history", {
    kind: "history",
    position: "last",
    fillRemaining: true,
  })
  .constraint("no-contradiction")
  .constraint("coverage")
  .constraint("max-redundancy", { threshold: 0.3 })
  .build();

const compiler = createContextCompiler();
const result = compiler.compile(program, {
  target: "claude",
  items: myItems,
  budget: { maxTokens: 8000 },
});

console.log(result.totalTokens); // tokens used
console.log(result.diagnostics); // constraint violations
console.log(result.optimizations); // passes applied
console.log(result.slots); // per-slot breakdown
```

## Slots

A slot declares a category of content your context needs.

| Slot Field      | Type                                     | Default      | Description                                       |
| --------------- | ---------------------------------------- | ------------ | ------------------------------------------------- |
| `name`          | `string`                                 | required     | Unique slot identifier                            |
| `kind`          | `string`                                 | required     | Matches `ContextItem.kind`                        |
| `required`      | `boolean`                                | `false`      | Error if no items fill this slot                  |
| `position`      | `'first' \| 'last' \| 'any'`             | `'any'`      | Where to place items in the final context         |
| `maxTokens`     | `number`                                 | budget limit | Per-slot token cap                                |
| `minTokens`     | `number`                                 | —            | Minimum tokens for this slot to be "satisfied"    |
| `fillRemaining` | `boolean`                                | `false`      | Gets leftover budget after other slots are filled |
| `strategy`      | `'priority' \| 'recency' \| 'relevance'` | `'priority'` | How to rank items within the slot                 |
| `deduplicate`   | `boolean`                                | `false`      | Remove items with >0.8 Jaccard overlap            |
| `maxStaleness`  | `number`                                 | —            | Prune items below this recency value              |

## Constraints

| Constraint           | What it checks                                                | Default Threshold |
| -------------------- | ------------------------------------------------------------- | ----------------- |
| `no-contradiction`   | Flags items with high word overlap but mismatched negations   | —                 |
| `freshness`          | Warns when item recency falls below threshold                 | `5`               |
| `coverage`           | Errors when required slots have no matching items             | —                 |
| `budget-utilization` | Warns when token usage is below threshold or dangerously high | `0.7`             |
| `max-redundancy`     | Warns when items have word overlap exceeding threshold        | `0.5`             |

## Compile Targets

| Target    | Optimisation Strategy                                               |
| --------- | ------------------------------------------------------------------- |
| `claude`  | U-shaped attention: high-priority items at start and end of context |
| `gpt4`    | Recency bias: high-priority items sorted to the start               |
| `gemini`  | Uniform attention: items grouped by kind                            |
| `generic` | No model-specific reordering                                        |

## API Reference

### `contextProgram(): ContextProgramBuilder`

Fluent builder for declaring programs. Chain `.declare()`, `.constraint()`, then `.build()`.

### `createContextCompiler(): ContextCompiler`

### `compiler.compile(program, options): CompileResult`

| Option        | Type            | Description                  |
| ------------- | --------------- | ---------------------------- |
| `target`      | `CompileTarget` | Target model family          |
| `items`       | `ContextItem[]` | Items to compile             |
| `budget`      | `Budget`        | Token budget                 |
| `packOptions` | `PackOptions`   | Options forwarded to ce-core |

### `CompileResult`

| Field           | Type                  | Description                                   |
| --------------- | --------------------- | --------------------------------------------- |
| `items`         | `ContextItem[]`       | Optimized items, ready to send                |
| `dropped`       | `ContextItem[]`       | Items that didn't fit                         |
| `totalTokens`   | `number`              | Total tokens used                             |
| `diagnostics`   | `CompileDiagnostic[]` | Constraint violations and warnings            |
| `optimizations` | `OptimizationPass[]`  | Which passes ran and what they affected       |
| `target`        | `CompileTarget`       | Target model                                  |
| `slots`         | `Record<string, ...>` | Per-slot item count, tokens, and satisfaction |
| `quality`       | `ContextQuality`      | Quality metrics from ce-core                  |

## Design Decisions

**Why a two-phase slot fill (required first, then fillRemaining)?** Required slots with explicit budgets get first priority, ensuring critical context (system prompts, active code) is never crowded out by history or retrieved documents. Slots with `fillRemaining: true` absorb whatever budget is left, which naturally adapts to the total context size.

**Why model-specific optimisation passes?** Different models attend to different positions in the context window. Claude exhibits U-shaped attention (strong at start and end), GPT-4 has a recency bias favouring the start, and Gemini's attention is more uniform. The compiler exploits these patterns by placing high-priority items where the model will attend most.

**Why four optimisation passes in sequence?** Staleness pruning runs first to remove dead weight. Deduplication follows to eliminate redundancy. Position-aware placement then orders items for the target model. Finally, cache-prefix ordering makes the first section deterministic so prompt caching can kick in across requests.

## Integration with Other Packages

### ce-core

The compiler uses `estimateTokens()` and `analyzeContext()` from ce-core for token counting and quality analysis. Quality metrics on the final result come directly from `analyzeContext()`.

### ce-adversarial

Run compiled context through adversarial probes to verify that the compiler's constraint checking catches injected attacks.

### ce-drift

Feed compiled results into the drift monitor to track quality trends over time and catch gradual degradation.

## License

MIT
