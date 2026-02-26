# @ce/providers

OpenAI and Anthropic provider adapters with token estimators for context engineering.

## Installation

```bash
npm install @ce/providers
```

Provider SDKs are optional peer dependencies -- install only what you use:

```bash
npm install openai             # for OpenAIProvider / OpenAIEmbeddingProvider
npm install @anthropic-ai/sdk  # for AnthropicProvider
```

## Quick Start

```ts
import { pack } from "@ce/core";
import { presets, OpenAIProvider } from "@ce/providers";

// Use accurate token estimation with packing
const result = pack(items, budget, {
  tokenEstimator: presets.openai.estimator,
});

// Use as an LLM provider
const llm = new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY });
const response = await llm.generate([{ role: "user", content: "Hello" }]);
```

## Token Estimators

| Export                    | Method                         | Accuracy             |
| ------------------------- | ------------------------------ | -------------------- |
| `openaiTokenEstimator`    | tiktoken (`cl100k_base`)       | Exact for GPT models |
| `anthropicTokenEstimator` | Word heuristic (`words * 1.4`) | Approximate          |

Both implement `TokenEstimator` from `@ce/core` and work with `pack()`.

## Presets

```ts
import { presets } from "@ce/providers";

presets.openai.estimator; // openaiTokenEstimator
presets.anthropic.estimator; // anthropicTokenEstimator
```

## LLM Providers

| Class               | SDK                 | Default Model                |
| ------------------- | ------------------- | ---------------------------- |
| `OpenAIProvider`    | `openai`            | `gpt-4o-mini`                |
| `AnthropicProvider` | `@anthropic-ai/sdk` | `claude-3-5-sonnet-20241022` |

Both implement the `LLMProvider` interface:

```ts
interface LLMProvider {
  generate(
    messages: LLMMessage[],
    options?: LLMGenerationOptions
  ): Promise<LLMResult>;
}
```

Options: `model`, `maxTokens`, `temperature`. API keys fall back to `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` env vars.

## Embedding Provider

| Class                     | SDK      | Default Model            |
| ------------------------- | -------- | ------------------------ |
| `OpenAIEmbeddingProvider` | `openai` | `text-embedding-3-small` |

```ts
interface EmbeddingProvider {
  embed(
    inputs: string[] | string,
    options?: EmbeddingOptions
  ): Promise<EmbeddingResult>;
}
```

## Model Metadata

```ts
import { MODEL_METADATA } from "@ce/providers";

MODEL_METADATA.openai["gpt-4o"].maxTokens; // 128000
MODEL_METADATA.anthropic["claude-3-5-sonnet-20241022"].maxTokens; // 200000
```

## License

MIT
