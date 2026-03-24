# Multi-Agent Entanglement

Context Entanglement (`ce-entangle`) solves the shared knowledge problem in multi-agent systems. When Agent A discovers something important, Agent B's next `pack()` automatically includes it — without B explicitly requesting it.

## The Problem

In multi-agent systems, agents operate independently with separate context windows. When Agent A discovers "the API endpoint moved to /v2", Agent B keeps generating code against /v1 until someone manually updates its context. Current solutions (shared databases, message passing) operate at the application layer and require explicit coordination.

## The Solution: Entanglement Mesh

A mesh connects agents at the context _packing_ layer. Entangled items are injected into `pack()` calls automatically, competing fairly with the agent's own items for budget space.

```ts
import { createEntanglementMesh } from "@context-engineering/entangle";

const mesh = createEntanglementMesh();

// Register agents
const research = mesh.register("research", { budget: { maxTokens: 8000 } });
const coding = mesh.register("coding", { budget: { maxTokens: 16000 } });

// Research agent discovers something important
research.entangle(
  {
    id: "api-change",
    content: "The /users endpoint now requires auth headers",
    priority: 9,
  },
  { scope: ["coding"], propagation: "immediate" }
);

// Coding agent's next pack automatically includes the discovery
const result = coding.pack(codingItems, { maxTokens: 16000 });
// result.entangledItems — shows what was injected from the mesh
// result.ownItems — the agent's original items
```

## Propagation Policies

| Policy      | Behavior                                          | Use case                          |
| ----------- | ------------------------------------------------- | --------------------------------- |
| `immediate` | Available right away, persists until acknowledged | Breaking changes, security alerts |
| `next-pack` | Available starting from the next `pack()` call    | Normal knowledge sharing          |
| `on-demand` | Only via `getPending()`, never auto-injected      | Low-priority FYI items            |

## Scope Control

Control which agents see which items:

```ts
// Only the coding agent sees this
research.entangle(item, { scope: ["coding"] });

// All agents see this
research.entangle(item, { scope: "*" });

// Multiple specific agents
research.entangle(item, { scope: ["coding", "testing", "review"] });
```

Agents never see their own entangled items — the mesh filters those out.

## Kind Filtering

Agents can filter by item kind:

```ts
const coding = mesh.register("coding", {
  budget: { maxTokens: 16000 },
  kindFilter: ["system", "tool", "retrieval"], // only these kinds
});
```

## TTL Expiry

Entangled items can expire:

```ts
research.entangle(item, { expiresIn: 300000 }); // expires in 5 minutes
```

Expired items are automatically excluded from future packs.

## Budget-Aware Injection

Entangled items don't bypass the budget — they're injected into the item list _before_ packing. The packer scores them alongside the agent's own items and selects the best combination within budget. High-priority entangled items will push low-priority own items out; low-priority entangled items may be dropped.

## Callbacks

```ts
const mesh = createEntanglementMesh({
  onEntangle: item =>
    console.log(`${item.sourceAgent} shared: ${item.item.id}`),
  onInject: (item, agent) =>
    console.log(`${item.item.id} injected into ${agent}`),
});
```

## State Persistence

```ts
// Export for storage
const state = mesh.exportState();
fs.writeFileSync("mesh-state.json", JSON.stringify(state));

// Restore later
const saved = JSON.parse(fs.readFileSync("mesh-state.json", "utf-8"));
mesh.importState(saved);
```
