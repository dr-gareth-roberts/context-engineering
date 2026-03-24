# Production Agent — Drift Monitoring, Immune System, and Time Travel

A self-contained simulation showing how the context engineering quality/safety packages work together in a long-running agent conversation.

## What it demonstrates

A 20-turn agent loop where context gradually degrades, and the system detects, recovers, and learns:

1. **Turns 1-5 (Healthy baseline):** High-quality context with system prompt, API docs, fresh conversation, and relevant code. Checkpointed as `healthy-baseline`.
2. **Turns 6-15 (Gradual degradation):** Each turn adds stale docs, redundant items, or irrelevant noise. The drift monitor tracks 6 quality dimensions and flags warnings, then critical alerts.
3. **Turn 16 (Recovery):** Drift triggers critical status. Time travel rewinds to the `healthy-baseline` checkpoint, fresh items are added, and quality is restored.
4. **Turns 17-18 (Adversarial testing):** Six attack types (contradiction, noise-flood, subtle-error, authority-spoof, temporal-poison, relevance-dilution) probe the pipeline for weaknesses. The worst vulnerability is recorded in the immune system.
5. **Turns 19-20 (Immune screening):** Future context packs are screened against learned failure patterns. The immune system fires antibodies when it detects a known-bad configuration.

## Packages used

- `@context-engineering/core` — `analyzeContext`, `pack`, `ContextItem`, `Budget`
- `@context-engineering/drift` — `createDriftMonitor` for continuous quality tracking
- `@context-engineering/time-travel` — `createTimeline` for checkpointing and rewinding
- `@context-engineering/immune` — `createImmuneSystem` for failure learning and screening
- `@context-engineering/adversarial` — `createAdversarialTester` for red-team probing

## Running

```bash
# From the repository root
pnpm install
pnpm run build:packages
npx tsx examples/production-agent/index.ts
```

## Output

The script prints a narrative showing turn-by-turn quality metrics, drift alerts, recovery steps, adversarial probe results, and immune system antibody activity. No external APIs are called — everything runs locally with simulated data.
