import Anthropic from "@anthropic-ai/sdk";
import type { LLMProvider, LLMResult, LLMMessage, LLMGenerationOptions } from "./types";

const DEFAULT_MODEL = "claude-3-5-sonnet-20241022";

export interface AnthropicProviderOptions {
  apiKey?: string;
  baseURL?: string;
}

export class AnthropicProvider implements LLMProvider {
  private client: Anthropic;

  constructor(options: AnthropicProviderOptions = {}) {
    this.client = new Anthropic({
      apiKey: options.apiKey ?? process.env.ANTHROPIC_API_KEY,
      baseURL: options.baseURL
    });
  }

  async generate(
    messages: LLMMessage[],
    options: LLMGenerationOptions = {}
  ): Promise<LLMResult> {
    const systemMessages = messages.filter((msg) => msg.role === "system");
    const system = systemMessages.map((msg) => msg.content).join("\n\n");
    const anthropicMessages = messages
      .filter((msg) => msg.role !== "system")
      .map((msg) => ({
        role: msg.role as "user" | "assistant",
        content: msg.content
      }));

    const response = await this.client.messages.create({
      model: options.model ?? DEFAULT_MODEL,
      max_tokens: options.maxTokens ?? 1024,
      temperature: options.temperature,
      system: system || undefined,
      messages: anthropicMessages
    });

    const text = response.content
      .map((block) => ("text" in block ? block.text : ""))
      .join("");

    const usage = response.usage
      ? {
          inputTokens: response.usage.input_tokens,
          outputTokens: response.usage.output_tokens,
          totalTokens: response.usage.input_tokens + response.usage.output_tokens
        }
      : undefined;

    return {
      text,
      model: response.model,
      usage
    };
  }
}
