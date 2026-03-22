import type { FrameworkMiddlewareOptions, GenericMessage } from "./types.js";
import { resolveConfig } from "./types.js";
import { packMessages, extractText } from "./shared.js";

/**
 * Duck-typed interface for a CrewAI-compatible LLM.
 * CrewAI uses LangChain models internally, so this supports both
 * `invoke` (LangChain-style) and `call` method signatures.
 */
export interface CrewAILike {
  call?(messages: unknown[], ...args: unknown[]): Promise<unknown>;
  invoke?(messages: unknown[], ...args: unknown[]): Promise<unknown>;
  model_name?: string;
  model?: string;
}

/** Extract model name from a CrewAI LLM object. */
function extractModelName(llm: CrewAILike): string {
  return llm.model_name ?? llm.model ?? "unknown";
}

/**
 * Extract role from a message that may be a LangChain class instance,
 * a plain object, or any duck-typed message.
 */
function extractRole(msg: unknown): string {
  if (typeof msg !== "object" || msg === null) return "user";
  const record = msg as Record<string, unknown>;

  // LangChain class-based _getType()
  if (typeof record._getType === "function") {
    const type = (record._getType as () => string)();
    if (type === "human") return "user";
    if (type === "ai") return "assistant";
    return type;
  }

  if (typeof record.type === "string") {
    if (record.type === "human") return "user";
    if (record.type === "ai") return "assistant";
    return record.type;
  }

  if (typeof record.role === "string") return record.role;
  return "user";
}

/** Convert unknown messages to GenericMessage[]. */
function toGenericMessages(messages: unknown[]): GenericMessage[] {
  return messages.map(raw => {
    const msg = raw as Record<string, unknown>;
    const role = extractRole(msg);
    const content = extractText(msg.content);
    return { role, content, _original: raw };
  });
}

/** Reconstruct original messages from packed GenericMessage[]. */
function fromGenericMessages(packed: GenericMessage[]): unknown[] {
  return packed.map(msg => {
    if (msg._original !== undefined) return msg._original;
    return { role: msg.role, content: msg.content };
  });
}

/**
 * Create an interceptor for a given method name.
 */
function createMethodInterceptor(
  target: CrewAILike,
  method: (...args: unknown[]) => Promise<unknown>,
  modelName: string,
  config: ReturnType<typeof resolveConfig>
) {
  return async function intercepted(
    messages: unknown[],
    ...rest: unknown[]
  ): Promise<unknown> {
    if (!Array.isArray(messages) || messages.length === 0) {
      return method.call(target, messages, ...rest);
    }

    try {
      const generic = toGenericMessages(messages);
      const { packed } = await packMessages(
        generic,
        modelName,
        "crewai",
        config
      );
      const reconstructed = fromGenericMessages(packed);
      return method.call(target, reconstructed, ...rest);
    } catch (error) {
      config.on.error?.(error);
      return method.call(target, messages, ...rest);
    }
  };
}

/**
 * Wrap a CrewAI-compatible LLM with context management.
 * Since CrewAI uses LangChain models internally, this wraps the model's
 * invoke/call method with the same approach as the LangChain adapter.
 *
 * @example
 * ```ts
 * import { withContextCrewAI } from '@context-engineering/frameworks';
 *
 * const managedLlm = withContextCrewAI(llm, { budget: 128_000 });
 * const agent = new Agent({ llm: managedLlm, ... });
 * ```
 */
export function withContextCrewAI<T extends CrewAILike>(
  llm: T,
  options?: FrameworkMiddlewareOptions
): T {
  const config = resolveConfig(options);
  const modelName = extractModelName(llm);

  return new Proxy(llm, {
    get(target, prop, receiver) {
      const value = Reflect.get(target, prop, receiver);

      if (prop === "invoke" && typeof value === "function") {
        return createMethodInterceptor(
          target,
          value as (...args: unknown[]) => Promise<unknown>,
          modelName,
          config
        );
      }

      if (prop === "call" && typeof value === "function") {
        return createMethodInterceptor(
          target,
          value as (...args: unknown[]) => Promise<unknown>,
          modelName,
          config
        );
      }

      return value;
    },
  });
}
