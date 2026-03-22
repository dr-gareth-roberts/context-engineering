import type { InterceptorOptions } from "./types.js";
import { resolveConfig } from "./types.js";
import { interceptMessages } from "./intercept.js";
import type { GenericMessage } from "./message-converter.js";

/**
 * Wrap an Anthropic client with automatic context management.
 *
 * Returns a proxy that intercepts `client.messages.create()` calls,
 * packing messages within the model's token budget before forwarding.
 *
 * Anthropic's API separates the system prompt from messages, so the interceptor
 * prepends the system prompt as a synthetic system message for scoring, then
 * strips it back out before forwarding.
 *
 * @example
 * ```ts
 * import Anthropic from '@anthropic-ai/sdk';
 * import { withContextAnthropic } from '@context-engineering/sdk-interceptors';
 *
 * const client = withContextAnthropic(new Anthropic(), { strategy: 'trim' });
 * // Use client.messages.create() as normal — context is managed automatically
 * ```
 */
export function withContextAnthropic<T extends object>(
  client: T,
  options?: InterceptorOptions
): T {
  const config = resolveConfig(options);

  return createAnthropicProxy(client, [], config);
}

function createAnthropicProxy<T extends object>(
  target: T,
  path: string[],
  config: ReturnType<typeof resolveConfig>
): T {
  return new Proxy(target, {
    get(obj, prop, receiver) {
      const value = Reflect.get(obj, prop, receiver);
      const propStr = typeof prop === "string" ? prop : "";
      const currentPath = [...path, propStr];
      const pathKey = currentPath.join(".");

      // Intercept messages.create
      if (pathKey === "messages.create" && typeof value === "function") {
        return createAnthropicInterceptor(value.bind(obj), config);
      }

      // Continue proxying for messages
      if (
        typeof value === "object" &&
        value !== null &&
        pathKey === "messages"
      ) {
        return createAnthropicProxy(value as object, currentPath, config);
      }

      return value;
    },
  });
}

function createAnthropicInterceptor(
  originalCreate: (...args: unknown[]) => unknown,
  config: ReturnType<typeof resolveConfig>
) {
  return async function interceptedCreate(
    params: Record<string, unknown>,
    ...rest: unknown[]
  ): Promise<unknown> {
    const messages = params.messages as GenericMessage[] | undefined;
    const model = (params.model as string) ?? "claude-sonnet-4-6";
    const systemPrompt = params.system as string | undefined;

    if (!messages || messages.length === 0) {
      return originalCreate(params, ...rest);
    }

    try {
      // Anthropic separates system from messages.
      // Prepend system as a synthetic message for unified scoring.
      const allMessages: GenericMessage[] = [];
      if (systemPrompt) {
        allMessages.push({ role: "system", content: systemPrompt });
      }
      allMessages.push(...messages);

      const packedMessages = await interceptMessages(
        allMessages,
        model,
        "anthropic",
        config
      );

      // Split system back out
      let newSystem = systemPrompt;
      let newMessages = packedMessages;

      if (systemPrompt && packedMessages.length > 0 && packedMessages[0].role === "system") {
        // The system message was kept (it always should be, with priority 100)
        const sysMsg = packedMessages[0];
        // Check if a summary was injected as a second system message
        if (
          packedMessages.length > 1 &&
          packedMessages[1].role === "system" &&
          typeof packedMessages[1].content === "string" &&
          packedMessages[1].content.startsWith("[Context summary")
        ) {
          // Append summary to system prompt
          newSystem = `${systemPrompt}\n\n${packedMessages[1].content}`;
          newMessages = packedMessages.slice(2);
        } else {
          newSystem = typeof sysMsg.content === "string" ? sysMsg.content : systemPrompt;
          newMessages = packedMessages.slice(1);
        }
      }

      return originalCreate(
        { ...params, system: newSystem, messages: newMessages },
        ...rest
      );
    } catch (error) {
      config.on.error?.(error);
      return originalCreate(params, ...rest);
    }
  };
}
