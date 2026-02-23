# Roadmap 01: Context Inspector (Observability UI)

## Objective

Provide developers with a visual debugging suite to inspect the "Context Packing" process, helping them understand why specific items were included, compressed, or dropped.

## Core Features

1.  **Waterfall Visualization:** A chronological or priority-sorted list of `ContextItems` showing the "Token Budget Drain."
2.  **Decision Rationale:** Tooltips or side panels explaining the "Why" (e.g., "Dropped: Score 0.45 < Threshold 0.5" or "Compressed: Priority low but content unique").
3.  **Interactive Budget Slider:** A "What-if" tool where developers can drag a slider to change the token budget and watch the context pack/unpack in real-time.
4.  **Trace Diffing:** Compare two different `ContextTraces` (e.g., before and after a prompt change).

## Technical Implementation (React/TypeScript)

- **Data Source:** Consumes the `ContextTrace` JSON schema already defined in `@ce/core`.
- **Components:**
  - `TraceTimeline`: A vertical list of steps from the `ContextTrace`.
  - `TokenBar`: A visual representation of the `maxTokens` vs `totalTokens` used.
  - `ItemDetailView`: A syntax-highlighted view of the item content and its metadata.
- **Integration:** Add a new route `/inspect` to the existing Vite application.

## Data Model Extensions

Enhance `TraceStep` in `packages/ce-core/src/types.ts` to include:

```typescript
interface TraceStep {
  // ... existing fields
  metrics: {
    priorityScore: number;
    recencyScore: number;
    salienceScore: number;
    finalRank: number;
  };
  comparison?: {
    supersededById?: string;
    duplicateOfId?: string;
  };
}
```

## Success Criteria

- Developers can identify the exact reason a "lost-in-the-middle" fact was dropped within 30 seconds of opening the inspector.
