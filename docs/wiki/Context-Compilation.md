# Context Compilation

The Context Compiler (`ce-compiler`) lets you declare _what_ your context should contain and _compiles_ it into an optimised layout for a specific target model — like a C compiler targeting x86 vs ARM.

## Why a Compiler?

The imperative `pipeline()` API requires you to specify _how_ to arrange context. The compiler inverts this: you declare intent (slots, constraints) and the compiler chooses the best strategy for each target.

This matters when:

- You target multiple models (compile once, deploy to Claude/GPT/Gemini with different optimisations)
- You want constraint enforcement (contradictions, freshness, coverage requirements)
- You want the system to choose strategies rather than specifying them

## Declaring a Program

```ts
import {
  contextProgram,
  createContextCompiler,
} from "@context-engineering/compiler";

const program = contextProgram()
  .declare("goal", { kind: "system", required: true, position: "first" })
  .declare("tools", { kind: "tool", required: true })
  .declare("history", {
    kind: "conversation",
    maxTokens: 2000,
    strategy: "recency",
  })
  .declare("docs", {
    kind: "retrieval",
    fillRemaining: true,
    deduplicate: true,
  })
  .constraint("coverage")
  .constraint("no-contradiction", { slots: ["docs", "history"] })
  .constraint("max-redundancy", { threshold: 0.3 })
  .constraint("budget-utilization", { threshold: 0.7 })
  .build();
```

### Slots

| Field           | Type                                     | Description                             |
| --------------- | ---------------------------------------- | --------------------------------------- |
| `kind`          | `string`                                 | Match items by `item.kind`              |
| `required`      | `boolean`                                | Error if no items match this slot       |
| `position`      | `"first" \| "last" \| "any"`             | Where in the context window             |
| `maxTokens`     | `number`                                 | Token ceiling for this slot             |
| `minTokens`     | `number`                                 | Token floor for this slot               |
| `fillRemaining` | `boolean`                                | Get leftover budget after other slots   |
| `strategy`      | `"priority" \| "recency" \| "relevance"` | How to rank items within slot           |
| `deduplicate`   | `boolean`                                | Remove >0.8 Jaccard overlap within slot |
| `maxStaleness`  | `number`                                 | Drop items below this recency threshold |

### Constraints

| Type                 | What it checks                                         |
| -------------------- | ------------------------------------------------------ |
| `coverage`           | All required slots have at least one item              |
| `no-contradiction`   | No items in specified slots have conflicting content   |
| `max-redundancy`     | No pair of items exceeds the Jaccard overlap threshold |
| `freshness`          | Items in specified slots have recency above threshold  |
| `budget-utilization` | Total tokens / budget is within acceptable range       |

## Compiling

```ts
const compiler = createContextCompiler();

const result = compiler.compile(program, {
  target: "claude", // or "gpt4", "gemini", "generic"
  items: allAvailableItems,
  budget: { maxTokens: 100000 },
});

console.log(result.items); // optimized context
console.log(result.diagnostics); // constraint violations
console.log(result.optimizations); // what passes were applied
console.log(result.slots); // per-slot breakdown
console.log(result.quality); // quality metrics
```

## Per-Model Optimisation

The compiler applies different optimisation passes per target:

| Pass                      | Claude                                | GPT-4               | Gemini          | Generic         |
| ------------------------- | ------------------------------------- | ------------------- | --------------- | --------------- |
| **Position placement**    | U-shaped (high priority at start+end) | Descending priority | Grouped by kind | Preserved order |
| **Cache prefix ordering** | By ID (deterministic prefix)          | By ID               | By ID           | By ID           |
| **Deduplication**         | Jaccard >0.8                          | Jaccard >0.8        | Jaccard >0.8    | Jaccard >0.8    |
| **Staleness pruning**     | By slot config                        | By slot config      | By slot config  | By slot config  |

## Diagnostics

Violations produce diagnostics with levels:

```ts
interface CompileDiagnostic {
  level: "info" | "warning" | "error";
  slot?: string;
  constraint?: string;
  message: string;
}
```

- `error`: Required slot empty, critical constraint violated
- `warning`: Constraint partially violated, low utilisation
- `info`: Optimisation applied, items deduplicated
