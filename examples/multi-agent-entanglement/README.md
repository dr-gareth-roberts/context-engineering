# Multi-Agent Entanglement — Shared Context via Pub/Sub Mesh

Demonstrates how multiple AI agents share context discoveries through an entanglement mesh without manual wiring.

## What it demonstrates

A feature development scenario where three agents collaborate on implementing OAuth2 PKCE:

1. **Mesh creation:** Three agents (researcher, coder, reviewer) registered with different token budgets and kind filters.
2. **Researcher discovers docs:** Finds OAuth2 RFC, Google OAuth guide, and security best practices. Shares with wildcard scope — all agents see them.
3. **Coder packs with injected docs:** When the coder calls `pack()`, the researcher's docs are automatically injected alongside the coder's own items. No explicit passing required.
4. **Coder shares implementation:** Writes PKCE utilities, provider configs, and secure token storage. Shares with scope `["reviewer"]` and a 1-hour TTL.
5. **Reviewer gets everything:** The reviewer's `pack()` includes their own checklist plus the researcher's docs and the coder's implementation — context flows from both sources.
6. **Scoped sharing:** A security note shared only with the reviewer is invisible to the coder, demonstrating fine-grained access control.
7. **Mesh statistics:** Item counts by source and scope.
8. **State export/import:** Full mesh state serialised and restored into a fresh instance.

## Key concepts

- **Entangle:** Publishing a context item to the mesh so other agents can see it
- **Scope:** `"*"` (all agents) or `["agent-b", "agent-c"]` (specific agents)
- **Kind filter:** Agents can opt in to only certain item kinds (e.g., coder only wants `docs` and `code`)
- **Propagation:** `"next-pack"` (default, injected on next `pack()` call) or `"immediate"`
- **TTL:** Items auto-expire after a duration — stale discoveries don't linger

## Packages used

- `@context-engineering/core` — `ContextItem` type definitions
- `@context-engineering/entangle` — `createEntanglementMesh`, agent handles, scoped sharing

## Running

```bash
# From the repository root
pnpm install
pnpm run build:packages
npx tsx examples/multi-agent-entanglement/index.ts
```

## Output

The script prints a step-by-step narrative showing how context flows between agents: what each agent shares, what each agent sees when packing, scoped visibility checks, mesh statistics, and state persistence. No external APIs are called — everything runs locally.
