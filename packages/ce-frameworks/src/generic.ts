import type { FrameworkMiddlewareOptions, GenericMessage } from "./types.js";
import { resolveConfig } from "./types.js";
import { packMessages } from "./shared.js";

/** Extended options for the generic adapter. */
export interface GenericMiddlewareOptions extends FrameworkMiddlewareOptions {
  /** Extract messages from method arguments */
  messageExtractor: (args: unknown[]) => GenericMessage[];
  /** Inject packed messages back into method arguments */
  messageInjector: (args: unknown[], packed: GenericMessage[]) => unknown[];
  /** Extract model name (optional) */
  modelExtractor?: (target: object) => string;
  /** Framework name for events (default: 'generic') */
  frameworkName?: string;
}

/**
 * Generic middleware that works with any object that has a method
 * accepting messages. Useful for custom or less common frameworks.
 *
 * @example
 * ```ts
 * const wrapped = withContextGeneric(myLlm, 'generate', {
 *   budget: 128_000,
 *   messageExtractor: (args) => args[0].messages,
 *   messageInjector: (args, packed) => [{ ...args[0], messages: packed }],
 * });
 * ```
 */
export function withContextGeneric<T extends object>(
  target: T,
  methodName: string,
  options: GenericMiddlewareOptions
): T {
  const {
    messageExtractor,
    messageInjector,
    modelExtractor,
    frameworkName,
    ...middlewareOptions
  } = options;

  const config = resolveConfig(middlewareOptions);
  const modelName = modelExtractor?.(target) ?? "unknown";
  const framework = frameworkName ?? "generic";

  return new Proxy(target, {
    get(obj, prop, receiver) {
      const value = Reflect.get(obj, prop, receiver);

      if (prop === methodName && typeof value === "function") {
        return async function interceptedMethod(
          ...args: unknown[]
        ): Promise<unknown> {
          try {
            const messages = messageExtractor(args);
            if (!Array.isArray(messages) || messages.length === 0) {
              return (value as (...a: unknown[]) => unknown).apply(obj, args);
            }

            const { packed } = await packMessages(
              messages,
              modelName,
              framework,
              config
            );
            const newArgs = messageInjector(args, packed);
            return (value as (...a: unknown[]) => unknown).apply(obj, newArgs);
          } catch (error) {
            config.on.error?.(error);
            // Graceful fallthrough
            return (value as (...a: unknown[]) => unknown).apply(obj, args);
          }
        };
      }

      return value;
    },
  });
}
