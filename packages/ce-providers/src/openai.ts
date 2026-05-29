import type OpenAI from "openai";
import type {
  EmbeddingOptions,
  EmbeddingProvider,
  EmbeddingResult,
  LLMProvider,
  LLMResult,
  LLMMessage,
  LLMGenerationOptions,
} from "./types.js";
import { createLazyClient } from "./lazy-client.js";

const DEFAULT_CHAT_MODEL = "gpt-4o-mini";
const DEFAULT_EMBED_MODEL = "text-embedding-3-small";

/**
 * Whether a model uses max_completion_tokens instead of the deprecated max_tokens.
 * Only o-series reasoning models require this parameter.
 * Uses prefix matching for robustness against date-suffixed variants (e.g. o3-mini-2025-01-31).
 * See: https://platform.openai.com/docs/api-reference/chat/create
 */
function usesMaxCompletionTokens(model: string): boolean {
  return /^o[134]-/.test(model) || model === "o1" || model === "o3";
}

export interface OpenAIProviderOptions {
  apiKey?: string;
  baseURL?: string;
  organization?: string;
}

function createOpenAIClient(
  options: OpenAIProviderOptions
): () => Promise<OpenAI> {
  return createLazyClient(() =>
    import("openai").then(({ default: OpenAIClient }) => {
      return new OpenAIClient({
        apiKey: options.apiKey ?? process.env.OPENAI_API_KEY,
        baseURL: options.baseURL ?? process.env.OPENAI_BASE_URL,
        organization: options.organization ?? process.env.OPENAI_ORG,
      });
    })
  );
}

export class OpenAIProvider implements LLMProvider {
  private getClient: () => Promise<OpenAI>;

  constructor(options: OpenAIProviderOptions = {}) {
    this.getClient = createOpenAIClient(options);
  }

  async generate(
    messages: LLMMessage[],
    options: LLMGenerationOptions = {}
  ): Promise<LLMResult> {
    if (!messages.length) {
      throw new Error("At least one message is required");
    }

    const client = await this.getClient();
    const model = options.model ?? DEFAULT_CHAT_MODEL;

    // Build request params with explicit stream: false to get ChatCompletion return type
    const params: OpenAI.Chat.Completions.ChatCompletionCreateParamsNonStreaming =
      {
        model,
        messages:
          messages as OpenAI.Chat.Completions.ChatCompletionMessageParam[],
        stream: false,
      };

    if (options.maxTokens !== undefined) {
      if (usesMaxCompletionTokens(model)) {
        params.max_completion_tokens = options.maxTokens;
      } else {
        params.max_tokens = options.maxTokens;
      }
    }

    if (options.temperature !== undefined) {
      params.temperature = options.temperature;
    }

    const completion = await client.chat.completions.create(params);

    const choice = completion.choices[0];
    const text = choice?.message?.content ?? "";
    const usage = completion.usage
      ? {
          inputTokens: completion.usage.prompt_tokens,
          outputTokens: completion.usage.completion_tokens,
          totalTokens: completion.usage.total_tokens,
        }
      : undefined;

    return {
      text,
      model: completion.model,
      usage,
    };
  }
}

export class OpenAIEmbeddingProvider implements EmbeddingProvider {
  private getClient: () => Promise<OpenAI>;

  constructor(options: OpenAIProviderOptions = {}) {
    this.getClient = createOpenAIClient(options);
  }

  async embed(
    inputs: string[] | string,
    options: EmbeddingOptions = {}
  ): Promise<EmbeddingResult> {
    const inputArray = Array.isArray(inputs) ? inputs : [inputs];
    const client = await this.getClient();
    const response = await client.embeddings.create({
      model: options.model ?? DEFAULT_EMBED_MODEL,
      input: inputArray,
    });

    // Order by the returned `index` before extracting vectors. OpenAI-compatible
    // gateways (Azure, LiteLLM, vLLM, etc.) may batch internally and return `data`
    // out of input order; consumers rely on strict positional correspondence
    // between vectors[i] and inputs[i]. No-op on the standard OpenAI endpoint.
    const ordered = [...response.data].sort((a, b) => a.index - b.index);
    return {
      vectors: ordered.map(item => item.embedding),
      model: response.model,
    };
  }
}
