# @context-engineering/entangle

Context Entanglement Mesh — scoped pub/sub for sharing context items across agents in multi-agent systems.

## Why

In multi-agent architectures, agents build context independently but often need to share discoveries. Agent A finds a critical code snippet that Agent B needs. Without a shared fabric, you either duplicate retrieval work or manually pipe context between agents. The entanglement mesh lets agents publish items with scoped visibility and propagation policies, then automatically injects relevant items during each agent's `pack()` call.

## Quick Start

```typescript
import { createEntanglementMesh } from "@context-engineering/entangle";

const mesh = createEntanglementMesh({
  defaultPropagation: "next-pack",
  maxItems: 500,
});

// Register agents
const coder = mesh.register("coder", {
  budget: { maxTokens: 8000 },
  kindFilter: ["code", "system"],
});

const reviewer = mesh.register("reviewer", {
  budget: { maxTokens: 4000 },
});

// Coder finds something the reviewer needs
coder.entangle(
  { id: "fix-1", content: "Found null check missing in auth.ts", kind: "code" },
  { scope: ["reviewer"], priority: 9 }
);

// Reviewer's next pack automatically includes the entangled item
const result = reviewer.pack(reviewerOwnItems);
console.log(result.entangledItems); // includes fix-1
console.log(result.ownItems); // reviewer's own items that were selected
```

## Propagation Policies

| Policy      | Behavior                                                                        |
| ----------- | ------------------------------------------------------------------------------- |
| `immediate` | Available right away. Persists until the receiving agent calls `acknowledge()`. |
| `next-pack` | Available starting from the next `pack()` call after entanglement.              |
| `on-demand` | Never auto-injected into `pack()`. Only accessible via `getPending()`.          |

## API Reference

### `createEntanglementMesh(config?): EntanglementMesh`

| Config Field         | Type                          | Default       | Description                                 |
| -------------------- | ----------------------------- | ------------- | ------------------------------------------- |
| `defaultPropagation` | `PropagationPolicy`           | `'next-pack'` | Default propagation for entangled items     |
| `defaultTTL`         | `number`                      | —             | Default TTL in milliseconds                 |
| `maxItems`           | `number`                      | `1000`        | Max items in the mesh (oldest pruned first) |
| `onEntangle`         | `(item) => void`              | —             | Called when an item is entangled            |
| `onInject`           | `(item, targetAgent) => void` | —             | Called when an item is injected into a pack |

### `EntanglementMesh` Methods

| Method                            | Description                                |
| --------------------------------- | ------------------------------------------ |
| `register(agentId, options?)`     | Register an agent, returns `AgentHandle`   |
| `getAgent(agentId)`               | Get an existing handle (or `null`)         |
| `listAgents()`                    | List all registered agents                 |
| `stats()`                         | Get mesh statistics (items, agents, scope) |
| `clear()`                         | Remove all entangled items                 |
| `exportState()` / `importState()` | Serialise/restore the mesh                 |

### `AgentHandle` Methods

| Method                           | Description                                         |
| -------------------------------- | --------------------------------------------------- |
| `entangle(item, options?)`       | Publish an item to the mesh                         |
| `pack(items, budget?, options?)` | Pack own items + entangled items from the mesh      |
| `getPending()`                   | Get entangled items for this agent without packing  |
| `acknowledge(...itemIds)`        | Mark items as acknowledged (for `immediate` policy) |
| `unregister()`                   | Remove this agent from the mesh                     |

### `EntangleOptions`

| Option        | Type                      | Default | Description                        |
| ------------- | ------------------------- | ------- | ---------------------------------- |
| `propagation` | `PropagationPolicy`       | config  | Override propagation for this item |
| `scope`       | `string[] \| '*'`         | `'*'`   | Which agents receive this item     |
| `expiresIn`   | `number`                  | —       | TTL in milliseconds from now       |
| `priority`    | `number`                  | —       | Override item priority             |
| `metadata`    | `Record<string, unknown>` | —       | Arbitrary metadata                 |

## Design Decisions

**Why scoped visibility instead of broadcast-only?** Broadcasting everything to every agent wastes token budget. A code analysis agent doesn't need design discussion context. Scoped visibility (`scope: ['reviewer']` or `scope: '*'`) lets publishers control who receives what, and `kindFilter` on registration lets consumers filter further.

**Why three propagation policies?** `immediate` is for urgent context (security findings, blocking errors). `next-pack` is the default for normal sharing — items appear naturally in the next packing cycle. `on-demand` is for low-priority items that agents can pull when they need them, without cluttering every pack.

**Why integrate at the `pack()` layer?** Injecting entangled items into `pack()` means they compete with the agent's own items for budget through the standard scoring mechanism. This prevents entangled items from overwhelming an agent's context — they only make it in if they score high enough to justify their token cost.

## Integration with Other Packages

### ce-core

Each agent's `pack()` call merges own items with entangled items and delegates to `pack()` from ce-core. The standard scoring, sorting, and budget enforcement applies to the combined set.

### ce-council

Use the mesh to share deliberation context between council members. One expert's key insight can be entangled and made available to all other members in subsequent rounds.

### ce-time-travel

Checkpoint the mesh state alongside timeline snapshots to create a complete record of cross-agent context sharing for debugging multi-agent workflows.

## License

MIT
