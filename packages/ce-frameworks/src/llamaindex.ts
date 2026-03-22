import type { FrameworkMiddlewareOptions, GenericMessage } from "./types.js";
import { resolveConfig } from "./types.js";
import { packMessages } from "./shared.js";

/**
 * Duck-typed interface for LlamaIndex LLM.
 * Matches any object with a `chat` method that accepts { messages }.
 */
export interface LlamaIndexLike {
  chat(params: {
    messages: LlamaIndexMessage[];
    [key: string]: unknown;
  }): Promise<unknown>;
  model?: string;
  metadata?: { model?: string; [key: string]: unknown };
}

/** Duck-typed LlamaIndex chat message. */
export interface LlamaIndexMessage {
  role: string;
  content: string;
  [key: string]: unknown;
}

/** Extract model name from a LlamaIndex LLM object. */
function extractModelName(llm: LlamaIndexLike): string {
  return llm.model ?? llm.metadata?.model ?? "unknown";
}

/** Convert LlamaIndex messages to GenericMessage[]. */
function toGenericMessages(messages: LlamaIndexMessage[]): GenericMessage[] {
  return messages.map(msg => ({
    role: msg.role,
    content:
      typeof msg.content === "string" ? msg.content : String(msg.content),
    _original: msg,
  }));
}

/** Reconstruct LlamaIndex messages from packed GenericMessage[]. */
function fromGenericMessages(packed: GenericMessage[]): LlamaIndexMessage[] {
  return packed.map(msg => {
    if (msg._original !== undefined) return msg._original as LlamaIndexMessage;
    return { role: msg.role, content: msg.content };
  });
}

/**
 * Wrap a LlamaIndex LLM with context management.
 * Works with any LLM that has a `chat` method accepting { messages }.
 *
 * @example
 * ```ts
 * import { OpenAI } from 'llamaindex';
 * import { withContextLlamaIndex } from '@context-engineering/frameworks';
 *
 * const llm = withContextLlamaIndex(new OpenAI({ model: 'gpt-4o' }), {
 *   budget: 128_000,
 * });
 * ```
 */
export function withContextLlamaIndex<T extends LlamaIndexLike>(
  llm: T,
  options?: FrameworkMiddlewareOptions
): T {
  const config = resolveConfig(options);
  const modelName = extractModelName(llm);

  return new Proxy(llm, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);

      if (prop === "chat" && typeof value === "function") {
        return async function interceptedChat(
          params: { messages: LlamaIndexMessage[]; [key: string]: unknown },
          ...rest: unknown[]
        ): Promise<unknown> {
          const messages = params?.messages;
          if (!Array.isArray(messages) || messages.length === 0) {
            return value.call(target, params, ...rest);
          }

          try {
            const generic = toGenericMessages(messages);
            const { packed } = await packMessages(
              generic,
              modelName,
              "llamaindex",
              config
            );
            const reconstructed = fromGenericMessages(packed);
            return value.call(
              target,
              { ...params, messages: reconstructed },
              ...rest
            );
          } catch (error) {
            config.on.error?.(error);
            return value.call(target, params, ...rest);
          }
        };
      }

      return value;
    },
  });
}
