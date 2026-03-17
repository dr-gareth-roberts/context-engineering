import type Anthropic from "@anthropic-ai/sdk";
import type {
  LLMProvider,
  LLMResult,
  LLMMessage,
  LLMGenerationOptions,
} from "./types.js";
import { createLazyClient } from "./lazy-client.js";

const DEFAULT_MODEL = "claude-sonnet-4-6";

export interface AnthropicProviderOptions {
  apiKey?: string;
  baseURL?: string;
}

export class AnthropicProvider implements LLMProvider {
  private getClient: () => Promise<Anthropic>;

  constructor(options: AnthropicProviderOptions = {}) {
    this.getClient = createLazyClient(() =>
      import("@anthropic-ai/sdk").then(({ default: AnthropicClient }) => {
        return new AnthropicClient({
          apiKey: options.apiKey ?? process.env.ANTHROPIC_API_KEY,
          baseURL: options.baseURL,
        });
      })
    );
  }

  async generate(
    messages: LLMMessage[],
    options: LLMGenerationOptions = {}
  ): Promise<LLMResult> {
    if (!messages.length) {
      throw new Error("At least one message is required");
    }

    const client = await this.getClient();
    const systemMessages = messages.filter(msg => msg.role === "system");
    const system = systemMessages.map(msg => msg.content).join("\n\n");
    const nonSystemMessages = messages.filter(msg => msg.role !== "system");

    // Validate that all non-system messages have roles supported by the
    // Anthropic API. With the widened LLMMessage.role type (M5), callers
    // can pass "tool" or arbitrary strings that would be silently cast.
    const SUPPORTED_ROLES = new Set(["user", "assistant"]);
    for (const msg of nonSystemMessages) {
      if (!SUPPORTED_ROLES.has(msg.role)) {
        throw new Error(
          `Unsupported message role "${msg.role}" for the Anthropic API. ` +
            `Only "user", "assistant", and "system" roles are supported.`
        );
      }
    }

    const anthropicMessages = nonSystemMessages.map(msg => ({
      role: msg.role as "user" | "assistant",
      content: msg.content,
    }));

    if (!anthropicMessages.length) {
      throw new Error(
        "At least one non-system message is required for the Anthropic API"
      );
    }

    // Build request params, only including defined optional fields
    const params: Record<string, unknown> = {
      model: options.model ?? DEFAULT_MODEL,
      max_tokens: options.maxTokens ?? 1024,
      messages: anthropicMessages,
    };

    if (system) {
      params.system = system;
    }

    if (options.temperature !== undefined) {
      params.temperature = options.temperature;
    }

    const response = await client.messages.create(
      params as Parameters<typeof client.messages.create>[0]
    );

    const text = response.content
      .map(block => ("text" in block ? block.text : ""))
      .join("");

    const usage = response.usage
      ? {
          inputTokens: response.usage.input_tokens,
          outputTokens: response.usage.output_tokens,
          totalTokens:
            response.usage.input_tokens + response.usage.output_tokens,
        }
      : undefined;

    return {
      text,
      model: response.model,
      usage,
    };
  }
}
