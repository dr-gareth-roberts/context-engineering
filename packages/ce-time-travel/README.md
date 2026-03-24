# @context-engineering/time-travel

Git-like branching, checkpointing, and merging for context state — fork experimental context configurations, compare them, and merge the best results back.

## Why

Context engineering is experimental by nature. You want to try adding retrieved documents, removing stale history, changing priority weights — and compare the results. Time travel gives you git semantics for context: branch, checkpoint, diff, and merge. Fork an experiment, run it, compare quality against main, and merge if it's better. All in-memory, no filesystem needed.

## Quick Start

```typescript
import { createTimeline } from "@context-engineering/time-travel";

const tl = createTimeline({ autoSnapshot: true });

// Set up initial context
tl.setItems([systemPrompt, codeContext, userMessage]);
tl.checkpoint("baseline");

// Try an experiment
tl.fork("with-docs");
tl.addItems(retrievedDoc1, retrievedDoc2);
tl.checkpoint("added-docs");

// Compare branches
tl.checkout("main");
const diff = tl.compare("main", "with-docs");
console.log(diff.onlyInBranch2); // items added in experiment
console.log(diff.quality1); // main quality metrics
console.log(diff.quality2); // experiment quality metrics

// Merge if the experiment is better
tl.merge("with-docs", {
  strategy: "best-quality",
  qualityDimension: "overall",
});
```

## Merge Strategies

| Strategy           | Behavior                                                               |
| ------------------ | ---------------------------------------------------------------------- |
| `union`            | Keep all items from both branches. Conflicts resolved by recency.      |
| `intersection`     | Keep only items present in both branches.                              |
| `best-quality`     | Keep the entire branch with better quality on a chosen dimension.      |
| `highest-priority` | For conflicts, keep the item with higher priority. Include all unique. |
| `manual`           | Pass a resolver function that receives both item sets.                 |

## API Reference

### `createTimeline(options?): Timeline`

| Option          | Type      | Default  | Description                          |
| --------------- | --------- | -------- | ------------------------------------ |
| `defaultBranch` | `string`  | `'main'` | Name of the initial branch           |
| `autoSnapshot`  | `boolean` | `false`  | Auto-checkpoint on every item change |
| `maxSnapshots`  | `number`  | —        | Prune oldest snapshots when exceeded |

### Item Management

| Method                | Description                             |
| --------------------- | --------------------------------------- |
| `getItems()`          | Get items on current branch (deep copy) |
| `setItems(items)`     | Replace items on current branch         |
| `addItems(...items)`  | Add items (skips duplicates by ID)      |
| `removeItems(...ids)` | Remove items by ID                      |

### Checkpoints & History

| Method                        | Description                                     |
| ----------------------------- | ----------------------------------------------- |
| `checkpoint(name, metadata?)` | Create a named snapshot on the current branch   |
| `rewind(nameOrId)`            | Restore current branch to a previous checkpoint |
| `history()`                   | Get all snapshots on the current branch         |
| `getSnapshot(nameOrId)`       | Look up a snapshot by name or ID                |

### Branching

| Method                            | Description                       |
| --------------------------------- | --------------------------------- |
| `fork(branchName, fromSnapshot?)` | Create and switch to a new branch |
| `checkout(branchName)`            | Switch to an existing branch      |
| `currentBranch()`                 | Get the active branch name        |
| `listBranches()`                  | List all branches                 |

### Comparison & Merging

| Method                        | Description                                 |
| ----------------------------- | ------------------------------------------- |
| `compare(branch1, branch2)`   | Diff two branches (items + quality metrics) |
| `merge(fromBranch, options?)` | Merge another branch into the current one   |

### `BranchComparison`

| Field           | Type               | Description                          |
| --------------- | ------------------ | ------------------------------------ |
| `onlyInBranch1` | `ContextItem[]`    | Items unique to branch 1             |
| `onlyInBranch2` | `ContextItem[]`    | Items unique to branch 2             |
| `common`        | `ContextItem[]`    | Items in both with identical content |
| `modified`      | `Array<{id, ...}>` | Same ID, different content           |
| `quality1`      | `ContextQuality`   | Quality metrics for branch 1         |
| `quality2`      | `ContextQuality`   | Quality metrics for branch 2         |

### `MergeResult`

| Field        | Type            | Description                                |
| ------------ | --------------- | ------------------------------------------ |
| `items`      | `ContextItem[]` | Merged items                               |
| `strategy`   | `MergeStrategy` | Strategy used                              |
| `fromBranch` | `string`        | Source branch                              |
| `intoBranch` | `string`        | Target branch                              |
| `added`      | `ContextItem[]` | Items added to the target                  |
| `removed`    | `ContextItem[]` | Items removed from the target              |
| `conflicts`  | `number`        | Number of same-ID, different-content items |

## Design Decisions

**Why deep copies everywhere?** Context items are mutable objects. Without deep copies, modifying an item on one branch would silently corrupt snapshots and other branches. Every `setItems()`, `fork()`, and `checkpoint()` call copies items to ensure complete isolation between branches and snapshots.

**Why five merge strategies?** `union` and `intersection` are the structural basics (include all vs. only shared). `best-quality` leverages ce-core's quality analysis for data-driven decisions. `highest-priority` resolves conflicts using the scoring system. `manual` is the escape hatch for cases where application-specific logic is needed.

**Why auto-snapshot as an option rather than default?** Auto-snapshots create a checkpoint on every mutation, which is valuable for debugging but has memory overhead. Most production uses only need explicit checkpoints at meaningful points (before experiments, after merges). The option lets you choose the tradeoff.

## Integration with Other Packages

### ce-core

Branch comparison uses `analyzeContext()` from ce-core to compute quality metrics for each branch. This enables data-driven merge decisions via the `best-quality` strategy.

### ce-compiler

Compile context on different branches and compare the results. Fork a branch, change the compilation target or slot configuration, and use `compare()` to see which approach produces better output.

### ce-drift

Checkpoint context state when drift is detected. Later, rewind to the last healthy checkpoint to understand what changed and restore good configurations.

## License

MIT
