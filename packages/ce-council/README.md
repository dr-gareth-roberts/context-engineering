# @context-engineering/council

Council of Experts — multi-model deliberation with structured debate strategies. Multiple LLM "experts" with distinct perspectives deliberate on a question through structured rounds, then a synthesizer merges the best insights into a single answer.

## Why

A single model gives you one perspective. A council gives you genuine intellectual tension — a security expert who challenges the architect, a pragmatist who grounds the innovator, a user advocate who keeps everyone honest. The context engineering toolkit manages the hard part: packing debate history into each participant's context window across rounds.

## Quick Start

```typescript
import { createCouncil, ROLE_PRESETS } from "@context-engineering/council";

const council = createCouncil({
  members: [
    {
      id: "arch",
      name: "Architect",
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
      name: "UX Designer",
      ...ROLE_PRESETS["user-advocate"],
      provider: anthropic,
      model: "claude-haiku-4-5",
    },
  ],
  strategy: "debate",
  rounds: 2,
  synthesizer: { provider: anthropic, model: "claude-opus-4-6" },
});

const result = await council.deliberate({
  query: "Should we use microservices or a modular monolith?",
  contextItems: architectureDocs,
  budget: { maxTokens: 8000 },
});

console.log(result.synthesis); // merged answer
console.log(result.totalTokens); // cost tracking
console.log(result.rounds); // full deliberation transcript
```

## Strategies

### `parallel`

All experts respond independently in a single round. No interaction. The synthesizer merges perspectives.

Best for: quick multi-perspective surveys, when you want diverse views without debate overhead.

### `debate`

Round 1: independent responses. Round 2+: each expert sees the others' previous responses and refines their position. Responses are attributed (experts know who said what).

Best for: deep analysis of contentious topics, when you want experts to challenge and build on each other's reasoning.

### `stepladder`

Experts enter one at a time. The first responds alone; the second sees the first's response and adds their view; the third sees both; and so on.

Based on the Stepladder Technique (Rogelberg et al., 1992). Prevents anchoring bias — each new member forms their independent opinion before seeing the group's.

Best for: reducing groupthink, when order of exposure matters, when you have experts of varying authority levels.

### `delphi`

Anonymous rounds. All experts respond independently, then see each other's responses without attribution, and revise. Continues until responses converge or max rounds is reached.

Based on the Delphi method (RAND Corporation). Anonymity prevents authority bias and status-driven conformity.

Best for: forecasting, risk assessment, when seniority differences might suppress dissent.

## API Reference

### `createCouncil(config: CouncilConfig): Council`

| Config Field           | Type                                                 | Default                    | Description                       |
| ---------------------- | ---------------------------------------------------- | -------------------------- | --------------------------------- |
| `members`              | `CouncilMember[]`                                    | required                   | At least 2 experts                |
| `strategy`             | `'parallel' \| 'debate' \| 'stepladder' \| 'delphi'` | required                   | Deliberation strategy             |
| `rounds`               | `number`                                             | `2` (debate), `3` (delphi) | Number of deliberation rounds     |
| `synthesizer`          | `{ provider, model?, maxTokens?, systemPrompt? }`    | required                   | Produces the final merged answer  |
| `convergenceThreshold` | `number`                                             | `0.8`                      | Delphi early-stop threshold (0-1) |
| `onMemberResponse`     | `(event) => void`                                    | —                          | Called after each member responds |
| `onRoundComplete`      | `(event) => void`                                    | —                          | Called after each round           |

### `council.deliberate(options): Promise<DeliberationResult>`

| Option         | Type            | Description                      |
| -------------- | --------------- | -------------------------------- |
| `query`        | `string`        | The question for deliberation    |
| `contextItems` | `ContextItem[]` | Context to pack for each member  |
| `budget`       | `Budget`        | Token budget for context packing |
| `packOptions`  | `PackOptions`   | Options forwarded to `pack()`    |
| `rounds`       | `number`        | Override rounds for this call    |

### `DeliberationResult`

| Field              | Type                     | Description                                 |
| ------------------ | ------------------------ | ------------------------------------------- |
| `synthesis`        | `string`                 | The final merged answer                     |
| `synthesisModel`   | `string`                 | Model used for synthesis                    |
| `rounds`           | `DeliberationRound[]`    | Full transcript of all rounds               |
| `totalTokens`      | `number`                 | Total tokens across all members + synthesis |
| `tokensByMember`   | `Record<string, number>` | Per-member token usage                      |
| `roundCount`       | `number`                 | Rounds executed                             |
| `strategy`         | `CouncilStrategy`        | Strategy used                               |
| `convergenceScore` | `number?`                | Final convergence (delphi)                  |
| `convergedEarly`   | `boolean?`               | Whether delphi stopped early                |
| `durationMs`       | `number`                 | Wall-clock time                             |

### `ROLE_PRESETS`

Pre-written system prompts for common expert archetypes:

| Preset            | Perspective                                                          |
| ----------------- | -------------------------------------------------------------------- |
| `critic`          | Finds flaws, edge cases, unstated assumptions                        |
| `optimist`        | Identifies opportunities and strengths                               |
| `pragmatist`      | Evaluates by implementation cost and operational risk                |
| `innovator`       | Thinks laterally, proposes unexpected alternatives                   |
| `domain-expert`   | Grounds discussion in technical reality                              |
| `devils-advocate` | Argues the opposing position to stress-test ideas                    |
| `user-advocate`   | Evaluates through the lens of user experience                        |
| `risk-analyst`    | Analyzes risk across technical, financial, and regulatory dimensions |

Use with spread syntax:

```typescript
{ id: "sec", name: "Security Lead", ...ROLE_PRESETS.critic, provider, model }
```

### `computeConvergence(responses: MemberResponse[]): number`

Compute average pairwise Jaccard similarity across all member responses. Returns 0-1 (1 = identical).

## Design Decisions

### Why duck-typed providers

`CouncilLLMProvider` matches the `LLMProvider` interface from `ce-providers` without importing it. This means ce-council has zero provider dependencies — use any LLM client that implements `generate(messages) → { text, model }`.

### Why structured strategies over freeform chat

Freeform multi-agent chat is hard to control and often devolves into agreement loops. Structured strategies (debate, stepladder, delphi) are backed by decades of group decision-making research and produce reliably diverse outputs. Each strategy has specific anti-bias properties.

### Why a separate synthesizer

The synthesis step uses a dedicated model call rather than asking one of the members to synthesize. This prevents any single expert's bias from dominating the final answer and allows using a more capable model for the high-stakes synthesis step.

### Why convergence detection for delphi

Real Delphi studies run until consensus. Token budgets make infinite rounds impractical, so we use Jaccard similarity as a cheap convergence proxy. When responses become sufficiently similar, additional rounds add cost without changing the outcome.

## Integration with Other Packages

### ce-core

Context items are packed via `pack()` before being sent to each member. The council manages context budgets so each expert gets the most relevant information within their model's window.

### ce-router

Route the synthesis step to the cheapest capable model:

```typescript
import { createContextRouter } from "@context-engineering/router";

const router = createContextRouter({ models });
const decision = router.route(contextItems, budget);

const council = createCouncil({
  // ... members ...
  synthesizer: {
    provider: providerForModel(decision.model),
    model: decision.model,
  },
});
```

### ce-adaptive

Feed deliberation quality back to the adaptive optimizer to learn which council configurations produce the best outcomes over time.

## License

MIT
