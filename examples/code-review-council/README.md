# Multi-Model Code Review Council

Demonstrates the `@context-engineering/council` package by assembling three
expert reviewers with distinct perspectives and running them through a
structured debate on a realistic code change.

## What it shows

- **Council of Experts** — three reviewers (Architect, Security Lead,
  Performance Engineer) with different role presets and mock LLM providers
- **Debate strategy** — experts see each other's responses after round 1
  and refine their positions in round 2, then a synthesiser merges everything
- **Delphi strategy** — the same experts deliberate anonymously, with
  convergence scoring that tracks how much agreement increases across rounds
- **Live callbacks** — `onMemberResponse` and `onRoundComplete` hooks show
  progress as the council runs
- **Token accounting** — per-expert and total token usage tracked across rounds

## Running it

```bash
npx tsx examples/code-review-council/index.ts
```

No API keys needed. The example uses mock providers with pre-written,
realistic review text so the council orchestration is the focus.

## Code structure

The script does the following:

1. Defines a realistic code diff (adding a user search API endpoint)
2. Creates three mock experts using `ROLE_PRESETS` from the council package
3. Runs a **debate** council (2 rounds) and prints each round's reviews,
   the synthesised final review, and token usage
4. Runs a **delphi** council (up to 3 rounds) on the same diff and prints
   convergence scores per round

## Swapping in real providers

Replace the mock providers with actual LLM clients:

```ts
import { createAnthropicProvider } from "@context-engineering/providers";

const claude = createAnthropicProvider({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

// Then use `provider: claude` instead of `provider: createMockProvider(...)`
```
