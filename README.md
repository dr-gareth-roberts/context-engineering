# Context Engineering Toolkit

[![CI](https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml/badge.svg)](https://github.com/dr-gareth-roberts/context-engineering/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/@context-engineering/core)](https://www.npmjs.com/package/@context-engineering/core)
[![PyPI](https://img.shields.io/pypi/v/context-engineering)](https://pypi.org/project/context-engineering/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Most LLM apps waste 30-50% of their context window on redundant, stale, or irrelevant content.** This toolkit fixes that.

17 TypeScript packages with full Python parity. 2,172 tests. MIT licensed.

---

## What it does

| Category         | Packages                                                                                                                                          | What they do                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **Core**         | [core](./packages/ce-core/) / [providers](./packages/ce-providers/) / [memory](./packages/ce-memory/) / [cli](./packages/ce-cli/)                 | Pack, score, diff, place, quality, cost, cache topology, BEADS handoff                    |
| **Multi-Model**  | [council](./packages/ce-council/) / [entangle](./packages/ce-entangle/) / [router](./packages/ce-router/)                                         | Multiple experts debate answers; agents share context via mesh; route to cheapest model   |
| **Quality**      | [adversarial](./packages/ce-adversarial/) / [immune](./packages/ce-immune/) / [debugger](./packages/ce-debugger/) / [drift](./packages/ce-drift/) | Red-team with 6 attacks; learn from failures; diagnose bad outputs; monitor degradation   |
| **Optimization** | [compiler](./packages/ce-compiler/) / [adaptive](./packages/ce-adaptive/) / [time-travel](./packages/ce-time-travel/)                             | Declarative context programs; learn weights from feedback; git-like checkpoint/fork/merge |
| **Integration**  | [sdk-interceptors](./packages/ce-sdk-interceptors/) / [frameworks](./packages/ce-frameworks/) / [rag](./packages/ce-rag/)                         | Drop-in OpenAI/Anthropic wrappers; LangChain/LlamaIndex middleware; info-gain retrieval   |

## Install

```bash
npm install @context-engineering/core    # TypeScript
pip install context-engineering          # Python
```

## Quick start

```ts
import { pack } from "@context-engineering/core";

const result = pack(
  [
    { id: "system", content: "You are a helpful assistant.", priority: 10 },
    { id: "docs", content: "API reference documentation...", priority: 7 },
    { id: "history", content: "Previous conversation...", priority: 3 },
    { id: "query", content: "How do I authenticate?", priority: 9 },
  ],
  { maxTokens: 4096 }
);

console.log(result.selected); // items that fit the budget
console.log(result.dropped); // items that didn't
```

Items are scored by `priority * 1.0 + recency * 0.7 + salience * 0.5`, sorted, and greedily selected until the budget is full.

## Why not just truncate?

| Approach                | What goes wrong                                          |
| ----------------------- | -------------------------------------------------------- |
| `messages.slice(-N)`    | Loses the system prompt after enough turns               |
| Truncate by token count | Drops high-value items randomly                          |
| Fixed sliding window    | Wastes budget on stale items while cutting relevant ones |

This toolkit scores every item, then selects the best combination within budget. It also optimizes for prefix cache reuse (up to 90% cost reduction), allocates budget across categories, monitors quality degradation, and red-teams your pipeline.

## Highlights

### Pipeline builder

```ts
const result = pipeline(8000)
  .add(systemPrompt, tools, documents)
  .allocate([
    { kind: "system", targetRatio: 0.15 },
    { kind: "retrieval", targetRatio: 0.55 },
    { kind: "conversation", targetRatio: 0.3 },
  ])
  .cacheTopology({ provider: "anthropic" })
  .qualityGate({ minOverall: 0.5 })
  .build();
```

### Council of Experts

3 models debate, then a synthesizer merges the best insights:

```ts
const council = createCouncil({
  members: [
    {
      id: "arch",
      name: "Architect",
      ...ROLE_PRESETS.pragmatist,
      provider: anthropic,
    },
    { id: "sec", name: "Security", ...ROLE_PRESETS.critic, provider: openai },
    {
      id: "ux",
      name: "UX",
      ...ROLE_PRESETS["user-advocate"],
      provider: anthropic,
    },
  ],
  strategy: "debate", // or "parallel", "stepladder", "delphi"
  rounds: 2,
  synthesizer: { provider: anthropic },
});

const result = await council.deliberate({
  query: "Microservices or monolith?",
});
```

### Adversarial testing

Red-team your context pipeline with 6 attack types:

```ts
const report = await tester.probe(items, budget, evaluator);
// report.overall: "resilient" | "vulnerable" | "critical"
```

### Context compiler

Declare what you want, compile per target model:

```ts
const program = contextProgram()
  .declare("goal", { kind: "system", required: true, position: "first" })
  .declare("docs", {
    kind: "retrieval",
    fillRemaining: true,
    deduplicate: true,
  })
  .constraint("coverage")
  .build();

const compiled = createContextCompiler().compile(program, {
  target: "claude",
  items,
  budget: { maxTokens: 100000 },
});
```

## Examples

Runnable demos, no API keys needed:

| Example                                                                         | Run                                             |
| ------------------------------------------------------------------------------- | ----------------------------------------------- |
| [RAG Chatbot](./examples/rag-chatbot/) — retrieval + info-gain + pipeline       | `npx tsx examples/rag-chatbot/index.ts`         |
| [Code Review Council](./examples/code-review-council/) — 3 experts debate a PR  | `npx tsx examples/code-review-council/index.ts` |
| [Production Agent](./examples/production-agent/) — drift + time-travel + immune | `npx tsx examples/production-agent/index.ts`    |

## Development

```bash
pnpm install && pnpm build:all    # TypeScript (1,264 tests across 17 packages)
cd python && pip install -e ".[dev]" && python -m pytest  # Python (908 tests)
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full guide. Browse the [Wiki](./docs/wiki/Home.md) for deep dives on each package.

## License

[MIT](./LICENSE)
