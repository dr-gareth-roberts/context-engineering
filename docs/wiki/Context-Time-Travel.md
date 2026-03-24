# Context Time Travel

Context Time Travel (`ce-time-travel`) provides git-like branching, forking, and merging of context states. Debug agent conversations by rewinding to where things went wrong, forking to try different approaches, and merging the best parts back.

## Core Operations

### Checkpoint & Rewind

```ts
import { createTimeline } from "@context-engineering/time-travel";

const timeline = createTimeline();

timeline.setItems([systemPrompt, docs, query]);
timeline.checkpoint("initial-setup");

// Agent does some work, context evolves
timeline.addItems(newRetrievalResults);
timeline.checkpoint("after-retrieval");

// Something went wrong — rewind
timeline.rewind("initial-setup");
// Context is back to the initial state
```

### Fork & Compare

```ts
// Try two different approaches
timeline.fork("approach-a");
timeline.setItems(approachAItems);
timeline.checkpoint("a-complete");

timeline.checkout("main");
timeline.fork("approach-b");
timeline.setItems(approachBItems);
timeline.checkpoint("b-complete");

// Compare branches
const comparison = timeline.compare("approach-a", "approach-b");
console.log(comparison.onlyInBranch1); // items unique to approach A
console.log(comparison.onlyInBranch2); // items unique to approach B
console.log(comparison.common); // shared items
console.log(comparison.modified); // same ID, different content
```

### Merge

```ts
// Merge approach-a into current branch
timeline.checkout("approach-b");
const result = timeline.merge("approach-a", {
  strategy: "best-quality",
  qualityDimension: "diversity",
});
console.log(result.added); // items gained from approach-a
console.log(result.removed); // items dropped during merge
console.log(result.conflicts); // items with same ID but different content
```

## Merge Strategies

| Strategy           | Behavior                                                                |
| ------------------ | ----------------------------------------------------------------------- |
| `union`            | Keep all items from both branches. Same ID → keep higher recency.       |
| `intersection`     | Keep only items present in both branches (by ID).                       |
| `best-quality`     | Run `analyzeContext()` on both, keep the set with better quality score. |
| `highest-priority` | For same-ID conflicts, keep the version with higher priority.           |
| `manual`           | Call your resolver function with both item sets.                        |

```ts
// Manual merge example
timeline.merge("other-branch", {
  strategy: "manual",
  resolver: (ours, theirs) => {
    // Custom logic — return the items you want
    return [
      ...ours.filter(i => i.priority > 5),
      ...theirs.filter(i => i.kind === "retrieval"),
    ];
  },
});
```

## Auto-Snapshot

```ts
const timeline = createTimeline({ autoSnapshot: true });

// Every setItems/addItems/removeItems automatically creates a snapshot
timeline.setItems(items1); // auto-snapshot created
timeline.addItems(item2); // auto-snapshot created
```

## Max Snapshots

```ts
const timeline = createTimeline({ maxSnapshots: 50 });
// Oldest snapshots are pruned when limit is exceeded
```

## State Persistence

```ts
// Export
const state = timeline.exportState();
fs.writeFileSync("timeline.json", JSON.stringify(state));

// Import
const saved = JSON.parse(fs.readFileSync("timeline.json", "utf-8"));
const restored = createTimeline();
restored.importState(saved);
```

## Use Cases

| Scenario                    | How to use                                           |
| --------------------------- | ---------------------------------------------------- |
| Debug a wrong answer        | Rewind to before the bad turn, inspect what changed  |
| A/B test context strategies | Fork, try different approaches, compare quality      |
| Safe experimentation        | Fork before making risky changes, merge if they work |
| Multi-step agent recovery   | Checkpoint at each step, rewind on failure           |
