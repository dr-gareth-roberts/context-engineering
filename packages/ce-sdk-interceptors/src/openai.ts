import type { InterceptorOptions } from "./types.js";
import { resolveConfig } from "./types.js";
import { interceptMessages } from "./intercept.js";
import type { GenericMessage } from "./message-converter.js";

/**
 * Wrap an OpenAI client with automatic context management.
 *
 * Returns a proxy that intercepts `client.chat.completions.create()` calls,
 * packing messages within the model's token budget before forwarding.
 *
 * @example
 * ```ts
 * import OpenAI from 'openai';
 * import { withContext } from '@context-engineering/sdk-interceptors';
 *
 * const client = withContext(new OpenAI(), { strategy: 'trim' });
 * // Use client.chat.completions.create() as normal — context is managed automatically
 * ```
 */
export function withContext<T extends object>(
  client: T,
  options?: InterceptorOptions
): T {
  const config = resolveConfig(options);

  // We need to intercept client.chat.completions.create()
  // Use a recursive Proxy that intercepts property access down the chain
  return createDeepProxy(client, [], config);
}

function createDeepProxy<T extends object>(
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

      // Intercept chat.completions.create
      if (
        pathKey === "chat.completions.create" &&
        typeof value === "function"
      ) {
        return createOpenAIInterceptor(value.bind(obj), config);
      }

      // Continue proxying down the chain for chat, chat.completions
      if (
        typeof value === "object" &&
        value !== null &&
        (pathKey === "chat" || pathKey === "chat.completions")
      ) {
        return createDeepProxy(value as object, currentPath, config);
      }

      return value;
    },
  });
}

function createOpenAIInterceptor(
  originalCreate: (...args: unknown[]) => unknown,
  config: ReturnType<typeof resolveConfig>
) {
  return async function interceptedCreate(
    params: Record<string, unknown>,
    ...rest: unknown[]
  ): Promise<unknown> {
    const messages = params.messages as GenericMessage[] | undefined;
    const model = (params.model as string) ?? "gpt-4o";

    if (!messages || messages.length === 0) {
      return originalCreate(params, ...rest);
    }

    try {
      const packedMessages = await interceptMessages(
        messages,
        model,
        "openai",
        config
      );

      return originalCreate({ ...params, messages: packedMessages }, ...rest);
    } catch (error) {
      config.on.error?.(error);
      // On packing failure, fall through to original call
      return originalCreate(params, ...rest);
    }
  };
}
