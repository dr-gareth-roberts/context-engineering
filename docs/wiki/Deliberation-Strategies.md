# Multi-Model Deliberation Strategies

The Council of Experts (`ce-council`) orchestrates multiple LLM "experts" with distinct perspectives through structured debate. Each expert has its own system prompt, model, and role. The toolkit manages context packing for each participant across rounds.

## Why Multiple Models?

A single model gives one perspective. A council surfaces genuine intellectual tension:

- A security expert challenges the architect
- A pragmatist grounds the innovator
- A user advocate keeps everyone honest
- A devil's advocate stress-tests consensus

The structured strategies below prevent the common failure modes of freeform multi-agent chat (agreement loops, authority bias, anchoring).

## The Four Strategies

### Parallel

All experts respond independently. No interaction. The synthesizer merges perspectives.

```
Round 1:  Expert A ──→ Response A
          Expert B ──→ Response B    ──→ Synthesizer ──→ Final Answer
          Expert C ──→ Response C
```

**Best for**: Quick surveys, diverse first impressions, when debate overhead isn't worth it.
**Anti-bias**: No interaction bias — each expert thinks independently.

### Debate

Round 1: independent responses. Round 2+: each expert sees the others' responses (with attribution) and refines their position.

```
Round 1:  A, B, C respond independently
Round 2:  A sees B+C → refines    B sees A+C → refines    C sees A+B → refines
          ──→ Synthesizer ──→ Final Answer
```

**Best for**: Contentious topics, when you want experts to challenge each other's reasoning.
**Anti-bias**: Forces explicit agreement/disagreement — no silent dissent.

### Stepladder

Based on [Rogelberg et al., 1992](https://en.wikipedia.org/wiki/Stepladder_technique). Experts enter one at a time. Each forms their independent opinion before seeing the group's.

```
Step 1:  A responds alone
Step 2:  B sees A's response → responds with fresh perspective
Step 3:  C sees A+B → responds with fresh perspective
         ──→ Synthesizer ──→ Final Answer
```

**Best for**: Reducing anchoring bias, when expert order matters, when you have varying authority levels.
**Anti-bias**: Each new member forms an independent opinion before seeing the group — prevents early speakers from anchoring the discussion.

### Delphi

Based on the [RAND Delphi method](https://en.wikipedia.org/wiki/Delphi_method). Anonymous rounds with convergence detection.

```
Round 1:  A, B, C respond independently (anonymous)
Round 2:  All see "Expert 1, Expert 2, Expert 3" (no names) → revise
Round 3:  If convergence > threshold → stop early
          ──→ Synthesizer ──→ Final Answer
```

**Best for**: Forecasting, risk assessment, when seniority differences might suppress dissent.
**Anti-bias**: Anonymity prevents authority bias and status-driven conformity.

## Convergence Detection

The Delphi strategy uses token-level Jaccard similarity to measure agreement:

```ts
const convergence = computeConvergence(responses);
// 0.0 = completely different responses
// 1.0 = identical responses
```

When convergence exceeds the threshold (default 0.8), additional rounds are skipped — they'd add cost without changing the outcome.

## Role Presets

Eight pre-written system prompts for common expert archetypes:

| Preset            | Perspective                                        |
| ----------------- | -------------------------------------------------- |
| `critic`          | Finds flaws, edge cases, unstated assumptions      |
| `optimist`        | Identifies opportunities and strengths             |
| `pragmatist`      | Evaluates by implementation cost and timeline      |
| `innovator`       | Thinks laterally, proposes unexpected alternatives |
| `domain-expert`   | Grounds discussion in technical reality            |
| `devils-advocate` | Argues the opposing position                       |
| `user-advocate`   | Evaluates through user experience lens             |
| `risk-analyst`    | Analyzes technical, financial, regulatory risk     |

## Example: Architecture Decision

```ts
import { createCouncil, ROLE_PRESETS } from "@context-engineering/council";

const council = createCouncil({
  members: [
    {
      id: "arch",
      name: "Lead Architect",
      ...ROLE_PRESETS.pragmatist,
      provider: anthropic,
      model: "claude-opus-4-6",
    },
    {
      id: "sec",
      name: "Security Lead",
      ...ROLE_PRESETS.critic,
      provider: openai,
      model: "gpt-4.1",
    },
    {
      id: "ux",
      name: "UX Director",
      ...ROLE_PRESETS["user-advocate"],
      provider: anthropic,
      model: "claude-haiku-4-5",
    },
  ],
  strategy: "debate",
  rounds: 2,
  synthesizer: { provider: anthropic, model: "claude-opus-4-6" },
  onRoundComplete: e =>
    console.log(`Round ${e.round}/${e.totalRounds} complete`),
});

const result = await council.deliberate({
  query:
    "Should we use microservices or a modular monolith for our e-commerce platform?",
  contextItems: [systemArchDocs, currentTrafficMetrics, teamCapabilities],
  budget: { maxTokens: 8000 },
});

console.log(result.synthesis); // merged answer
console.log(result.roundCount); // 2
console.log(result.totalTokens); // cost tracking
console.log(result.tokensByMember); // per-expert breakdown
```

## Choosing a Strategy

| Situation                      | Strategy           | Why                           |
| ------------------------------ | ------------------ | ----------------------------- |
| Quick multi-perspective survey | parallel           | No debate overhead            |
| Technical design decisions     | debate             | Experts challenge each other  |
| Risk assessment, forecasting   | delphi             | Anonymous, convergence-based  |
| Junior + senior experts        | stepladder         | Prevents anchoring by seniors |
| Time-sensitive decisions       | parallel           | Single round                  |
| High-stakes decisions          | debate (3+ rounds) | Maximum scrutiny              |
