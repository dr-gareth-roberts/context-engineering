import OpenAI from "openai";
import type {
  EmbeddingProvider,
  EmbeddingResult,
  LLMProvider,
  LLMResult,
  LLMMessage,
  LLMGenerationOptions,
} from "./types";

const DEFAULT_CHAT_MODEL = "gpt-4o-mini";
const DEFAULT_EMBED_MODEL = "text-embedding-3-small";

export interface OpenAIProviderOptions {
  apiKey?: string;
  baseURL?: string;
  organization?: string;
}

export class OpenAIProvider implements LLMProvider {
  private client: OpenAI;

  constructor(options: OpenAIProviderOptions = {}) {
    this.client = new OpenAI({
      apiKey: options.apiKey ?? process.env.OPENAI_API_KEY,
      baseURL: options.baseURL ?? process.env.OPENAI_BASE_URL,
      organization: options.organization ?? process.env.OPENAI_ORG,
    });
  }

  async generate(
    messages: LLMMessage[],
    options: LLMGenerationOptions = {}
  ): Promise<LLMResult> {
    const response = await this.client.chat.completions.create({
      model: options.model ?? DEFAULT_CHAT_MODEL,
      messages,
      max_tokens: options.maxTokens,
      temperature: options.temperature,
    });

    const choice = response.choices[0];
    const text = choice?.message?.content ?? "";
    const usage = response.usage
      ? {
          inputTokens: response.usage.prompt_tokens,
          outputTokens: response.usage.completion_tokens,
          totalTokens: response.usage.total_tokens,
        }
      : undefined;

    return {
      text,
      model: response.model,
      usage,
    };
  }
}

export class OpenAIEmbeddingProvider implements EmbeddingProvider {
  private client: OpenAI;

  constructor(options: OpenAIProviderOptions = {}) {
    this.client = new OpenAI({
      apiKey: options.apiKey ?? process.env.OPENAI_API_KEY,
      baseURL: options.baseURL ?? process.env.OPENAI_BASE_URL,
      organization: options.organization ?? process.env.OPENAI_ORG,
    });
  }

  async embed(
    inputs: string[] | string,
    options: { model?: string } = {}
  ): Promise<EmbeddingResult> {
    const inputArray = Array.isArray(inputs) ? inputs : [inputs];
    const response = await this.client.embeddings.create({
      model: options.model ?? DEFAULT_EMBED_MODEL,
      input: inputArray,
    });

    return {
      vectors: response.data.map(item => item.embedding),
      model: response.model,
    };
  }
}
