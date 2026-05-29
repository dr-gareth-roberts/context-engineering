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
  return function interceptedCreate(
    params: Record<string, unknown>,
    ...rest: unknown[]
  ): ApiPromiseShim {
    // Resolve to a holder carrying the APIPromise from originalCreate. The
    // holder is essential: returning the APIPromise directly from an async
    // function would adopt (await) it, unwrapping it to its resolved value and
    // discarding the SDK helper methods. Wrapping it in `{ call }` keeps the
    // APIPromise object intact so `.withResponse()`/`.asResponse()` can reach
    // through to the real methods after packing resolves.
    const apiCall: Promise<{ call: unknown }> = (async () => {
      const messages = params.messages as GenericMessage[] | undefined;
      const model = (params.model as string) ?? "claude-sonnet-4-6";
      const systemPrompt = params.system as string | undefined;

      if (!messages || messages.length === 0) {
        return { call: originalCreate(params, ...rest) };
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

        if (
          systemPrompt &&
          packedMessages.length > 0 &&
          packedMessages[0].role === "system"
        ) {
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
            newSystem =
              typeof sysMsg.content === "string"
                ? sysMsg.content
                : systemPrompt;
            newMessages = packedMessages.slice(1);
          }
        } else if (
          !systemPrompt &&
          packedMessages.length > 0 &&
          packedMessages[0].role === "system" &&
          typeof packedMessages[0].content === "string" &&
          packedMessages[0].content.startsWith("[Context summary")
        ) {
          // No top-level system prompt: the summarize strategy injected a
          // synthetic system message at index 0. Anthropic forbids role:"system"
          // inside the messages array, so fold it into the top-level system param.
          newSystem = packedMessages[0].content;
          newMessages = packedMessages.slice(1);
        }

        return {
          call: originalCreate(
            { ...params, system: newSystem, messages: newMessages },
            ...rest
          ),
        };
      } catch (error) {
        config.on.error?.(error);
        return { call: originalCreate(params, ...rest) };
      }
    })();

    // Build the Promise/helper chains lazily, per method call. Returning `call`
    // from `.then(({ call }) => call)` adopts the APIPromise, so awaiting the
    // shim yields the resolved body (or Stream for streaming calls), unchanged.
    //
    // Crucially, nothing is created eagerly: a caller that uses only
    // `.withResponse()`/`.asResponse()` never builds the `then`/`catch`/`finally`
    // chain, so a rejecting API call cannot leave a floating, unhandled promise
    // (which would crash the process under Node's default unhandled-rejection
    // policy). Each method attaches exactly one handler chain to `apiCall`.
    return {
      then: (onFulfilled, onRejected) =>
        apiCall.then(({ call }) => call).then(onFulfilled, onRejected),
      catch: onRejected => apiCall.then(({ call }) => call).catch(onRejected),
      finally: onFinally => apiCall.then(({ call }) => call).finally(onFinally),
      // Forward the public APIPromise helpers through the holder, which still
      // carries the real APIPromise even though awaiting unwraps it.
      withResponse: () => apiCall.then(({ call }) => callWithResponse(call)),
      asResponse: () => apiCall.then(({ call }) => callAsResponse(call)),
    };
  };
}

type FulfilledHandler = ((value: unknown) => unknown) | null | undefined;
type RejectedHandler = ((reason: unknown) => unknown) | null | undefined;

/**
 * Thenable returned by the wrapped `create()`. It is awaitable like the SDK's
 * APIPromise (so `await create(...)` still yields the body, or a Stream for
 * streaming calls), and additionally forwards the two public APIPromise helpers
 * callers rely on: `.withResponse()` and `.asResponse()`. Private APIPromise
 * members (`.parse()`, `._thenUnwrap`) are intentionally not forwarded, since
 * they are not part of the SDK's public contract.
 */
interface ApiPromiseShim {
  then: (
    onFulfilled?: FulfilledHandler,
    onRejected?: RejectedHandler
  ) => Promise<unknown>;
  catch: (onRejected?: RejectedHandler) => Promise<unknown>;
  finally: (onFinally?: (() => void) | null | undefined) => Promise<unknown>;
  withResponse: () => Promise<unknown>;
  asResponse: () => Promise<unknown>;
}

function callWithResponse(call: unknown): unknown {
  return (call as { withResponse: () => unknown }).withResponse();
}

function callAsResponse(call: unknown): unknown {
  return (call as { asResponse: () => unknown }).asResponse();
}
