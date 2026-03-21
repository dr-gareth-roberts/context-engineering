# @context-engineering/providers

OpenAI and Anthropic provider adapters with token estimators for context engineering.

## Installation

```bash
npm install @context-engineering/providers
```

Provider SDKs are optional peer dependencies -- install only what you use:

```bash
npm install openai             # for OpenAIProvider / OpenAIEmbeddingProvider
npm install @anthropic-ai/sdk  # for AnthropicProvider
```

## Quick Start

```ts
import { pack } from "@context-engineering/core";
import { presets, OpenAIProvider } from "@context-engineering/providers";

// Use accurate token estimation with packing
const result = pack(items, budget, {
  tokenEstimator: presets.openai.estimator,
});

// Use as an LLM provider
const llm = new OpenAIProvider({ apiKey: process.env.OPENAI_API_KEY });
const response = await llm.generate([{ role: "user", content: "Hello" }]);
```

## Token Estimators

| Export                    | Method                                                                | Accuracy             |
| ------------------------- | --------------------------------------------------------------------- | -------------------- |
| `openaiTokenEstimator`    | tiktoken (`o200k_base`, falls back to `cl100k_base` for older models) | Exact for GPT models |
| `anthropicTokenEstimator` | Word heuristic (`words * 1.4`)                                        | Approximate          |

Both implement `TokenEstimator` from `@context-engineering/core` and work with `pack()`.

## Presets

```ts
import { presets } from "@context-engineering/providers";

presets.openai.estimator; // openaiTokenEstimator
presets.anthropic.estimator; // anthropicTokenEstimator
```

## LLM Providers

| Class               | SDK                 | Default Model       |
| ------------------- | ------------------- | ------------------- |
| `OpenAIProvider`    | `openai`            | `gpt-4o-mini`       |
| `AnthropicProvider` | `@anthropic-ai/sdk` | `claude-sonnet-4-6` |

Both implement the `LLMProvider` interface:

```ts
interface LLMProvider {
  generate(
    messages: LLMMessage[],
    options?: LLMGenerationOptions
  ): Promise<LLMResult>;
}
```

### OpenAIProvider Options

| Option         | Description                          | Env Var Fallback  |
| -------------- | ------------------------------------ | ----------------- |
| `apiKey`       | OpenAI API key                       | `OPENAI_API_KEY`  |
| `baseURL`      | Custom API base URL                  | `OPENAI_BASE_URL` |
| `organization` | OpenAI organization ID               | `OPENAI_ORG`      |
| `model`        | Model to use (default `gpt-4o-mini`) | —                 |
| `maxTokens`    | Maximum tokens in response           | —                 |
| `temperature`  | Sampling temperature                 | —                 |

### AnthropicProvider Options

| Option        | Description                                | Env Var Fallback    |
| ------------- | ------------------------------------------ | ------------------- |
| `apiKey`      | Anthropic API key                          | `ANTHROPIC_API_KEY` |
| `baseURL`     | Custom API base URL                        | —                   |
| `model`       | Model to use (default `claude-sonnet-4-6`) | —                   |
| `maxTokens`   | Maximum tokens in response                 | —                   |
| `temperature` | Sampling temperature                       | —                   |

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

## Utility Exports

```ts
import {
  createLLMSummarizer,
  adaptEmbeddingProvider,
  createLazyClient,
} from "@context-engineering/providers";
```

| Export                             | Description                                                                       |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| `createLLMSummarizer(provider)`    | Creates an `AsyncSummarizer` compatible with ce-core, wrapping an `LLMProvider`   |
| `adaptEmbeddingProvider(provider)` | Bridges ce-providers `EmbeddingProvider` to ce-core `EmbeddingProvider` interface |
| `createLazyClient(factory)`        | Lazy-initializes API clients on first use                                         |

## Model Metadata

```ts
import { MODEL_METADATA } from "@context-engineering/providers";

MODEL_METADATA.openai["gpt-4o"].maxTokens; // 128000
MODEL_METADATA.anthropic["claude-sonnet-4-6"].maxTokens; // 200000
```

## License

MIT
