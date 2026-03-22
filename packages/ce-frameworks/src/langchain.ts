import type { FrameworkMiddlewareOptions, GenericMessage } from "./types.js";
import { resolveConfig } from "./types.js";
import { packMessages, extractText } from "./shared.js";

/**
 * Duck-typed interface for LangChain ChatModel.
 * Matches any object with an `invoke` method that accepts message arrays.
 */
export interface LangChainLike {
  invoke(messages: unknown[], config?: unknown): Promise<unknown>;
  model_name?: string;
  modelName?: string;
}

/**
 * Duck-typed LangChain message. Supports both class-based (with _getType)
 * and plain object formats.
 */
export interface LangChainMessage {
  content: string | unknown;
  _getType?: () => string;
  role?: string;
  type?: string;
  [key: string]: unknown;
}

/** Extract the role from a LangChain message using available fields. */
function extractRole(msg: LangChainMessage): string {
  // Class-based messages use _getType()
  if (typeof msg._getType === "function") {
    const type = msg._getType();
    // LangChain types: 'human' -> 'user', 'ai' -> 'assistant'
    if (type === "human") return "user";
    if (type === "ai") return "assistant";
    return type;
  }
  // Plain object messages
  if (typeof msg.type === "string") {
    if (msg.type === "human") return "user";
    if (msg.type === "ai") return "assistant";
    return msg.type;
  }
  if (typeof msg.role === "string") return msg.role;
  return "user";
}

/** Extract model name from a LangChain model object. */
function extractModelName(model: LangChainLike): string {
  return model.model_name ?? model.modelName ?? "unknown";
}

/** Convert LangChain messages to GenericMessage[]. */
function toGenericMessages(messages: unknown[]): GenericMessage[] {
  return messages.map(raw => {
    const msg = raw as LangChainMessage;
    const role = extractRole(msg);
    const content = extractText(msg.content);
    return { role, content, _original: raw };
  });
}

/** Reconstruct original LangChain messages from packed GenericMessage[]. */
function fromGenericMessages(packed: GenericMessage[]): unknown[] {
  return packed.map(msg => {
    // If we have the original LangChain message object, use it
    if (msg._original !== undefined) return msg._original;
    // Otherwise return a plain object (e.g. injected summary messages)
    return { role: msg.role, content: msg.content };
  });
}

/**
 * Wrap a LangChain ChatModel with context management.
 * Works with any ChatModel that has an `invoke` method accepting BaseMessage[].
 *
 * @example
 * ```ts
 * import { ChatOpenAI } from '@langchain/openai';
 * import { withContextLangChain } from '@context-engineering/frameworks';
 *
 * const model = withContextLangChain(new ChatOpenAI({ model: 'gpt-4o' }), {
 *   budget: 128_000,
 *   strategy: 'trim',
 * });
 * // Use model.invoke() as normal — context is managed automatically
 * ```
 */
export function withContextLangChain<T extends LangChainLike>(
  model: T,
  options?: FrameworkMiddlewareOptions
): T {
  const config = resolveConfig(options);
  const modelName = extractModelName(model);

  return new Proxy(model, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);

      if (prop === "invoke" && typeof value === "function") {
        return async function interceptedInvoke(
          messages: unknown[],
          ...rest: unknown[]
        ): Promise<unknown> {
          if (!Array.isArray(messages) || messages.length === 0) {
            return value.call(target, messages, ...rest);
          }

          try {
            const generic = toGenericMessages(messages);
            const { packed } = await packMessages(
              generic,
              modelName,
              "langchain",
              config
            );
            const reconstructed = fromGenericMessages(packed);
            return value.call(target, reconstructed, ...rest);
          } catch (error) {
            config.on.error?.(error);
            // Graceful fallthrough: call original on failure
            return value.call(target, messages, ...rest);
          }
        };
      }

      return value;
    },
  });
}
