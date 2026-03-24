# @context-engineering/adversarial

Adversarial testing for context pipelines — inject attacks into your context items and measure how much quality degrades.

## Why

Your context pipeline will encounter poisoned, contradictory, and noisy inputs in production. Testing only with clean data means your first encounter with adversarial content happens in front of users. This package lets you stress-test your packing pipeline against six categories of attack, using a deterministic seeded PRNG so results are reproducible.

## Quick Start

```typescript
import { createAdversarialTester } from "@context-engineering/adversarial";
import { pack } from "@context-engineering/core";

const tester = createAdversarialTester({
  attacks: ["contradiction", "noise-flood", "authority-spoof"],
  probeRounds: 3,
});

const report = await tester.probe(
  contextItems,
  { maxTokens: 4000 },
  async packed => {
    // Your quality evaluator: return 0-1
    const response = await llm.generate(packed);
    return scoreResponse(response);
  }
);

console.log(report.overall); // 'resilient' | 'vulnerable' | 'critical'
console.log(report.worstAttack); // which attack caused the most damage
console.log(report.attacks); // per-attack breakdown
```

## Attack Types

| Attack               | What it does                                                                 |
| -------------------- | ---------------------------------------------------------------------------- |
| `contradiction`      | Injects items that directly contradict existing context                      |
| `noise-flood`        | Floods context with plausible-sounding but irrelevant filler                 |
| `subtle-error`       | Clones items with small mutations (swapped operators, negated conditions)    |
| `authority-spoof`    | Injects high-priority system directives with dangerous advice                |
| `temporal-poison`    | Manipulates recency and `supersedes` fields to confuse temporal ordering     |
| `relevance-dilution` | Floods with off-topic items to push relevant content out of the token budget |

## API Reference

### `createAdversarialTester(config): AdversarialTester`

| Config Field  | Type                             | Default  | Description                  |
| ------------- | -------------------------------- | -------- | ---------------------------- |
| `attacks`     | `(AttackType \| AttackConfig)[]` | required | Attacks to run               |
| `probeRounds` | `number`                         | `3`      | Rounds per attack (averaged) |

Each attack can be a string (`'noise-flood'`) or an object with intensity control:

```typescript
{ type: 'contradiction', intensity: 0.8 } // 0-1, higher = more aggressive
```

### `tester.probe(items, budget, evaluator, options?): Promise<ProbeReport>`

Runs all configured attacks. For each attack, injects adversarial items, packs via `pack()`, and calls your evaluator to measure quality degradation.

### `ProbeReport`

| Field             | Type                                        | Description                                 |
| ----------------- | ------------------------------------------- | ------------------------------------------- |
| `overall`         | `'resilient' \| 'vulnerable' \| 'critical'` | Worst severity across all attacks           |
| `baselineQuality` | `number`                                    | Quality score with clean inputs             |
| `worstAttack`     | `AttackResult \| null`                      | Attack that caused the largest quality drop |
| `attacks`         | `AttackResult[]`                            | Per-attack results                          |
| `totalProbes`     | `number`                                    | Total evaluator calls made                  |
| `durationMs`      | `number`                                    | Wall-clock time                             |

### `applyAttack(type, items, intensity, seed): ContextItem[]`

Apply a single attack directly. Pure function — deterministic given the same inputs.

## Design Decisions

**Why a seeded PRNG instead of `Math.random()`?** Adversarial tests must be reproducible. If an attack reveals a vulnerability, you need to reproduce it exactly while you fix the pipeline. The mulberry32 PRNG produces identical attack payloads given the same seed.

**Why measure quality degradation instead of pass/fail?** A 5% quality drop from noise injection is normal and healthy. A 40% drop from authority spoofing is critical. The severity thresholds (`< 0.1` resilient, `0.1-0.3` vulnerable, `> 0.3` critical) classify the gradient rather than forcing a binary.

**Why six specific attacks?** These cover the most common failure modes in RAG and context assembly: contradictory sources, noisy retrieval, subtle data corruption, prompt injection via priority gaming, temporal confusion, and relevance flooding. Custom attacks can be added by implementing the `AttackFunction` signature.

## Integration with Other Packages

### ce-core

Attacks are applied to raw `ContextItem[]` arrays, then packed via `pack()` before evaluation. This tests your full pipeline — scoring, sorting, and budget enforcement — not just the raw items.

### ce-immune

Feed `ProbeReport` results into the immune system to create antibodies for attack patterns that caused critical failures. Future context packs matching those patterns will be flagged before reaching production.

## License

MIT
