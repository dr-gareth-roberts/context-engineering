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
      const model = (params.model as string) ?? "gpt-4o";

      if (!messages || messages.length === 0) {
        return { call: originalCreate(params, ...rest) };
      }

      try {
        const packedMessages = await interceptMessages(
          messages,
          model,
          "openai",
          config
        );

        return {
          call: originalCreate(
            { ...params, messages: packedMessages },
            ...rest
          ),
        };
      } catch (error) {
        config.on.error?.(error);
        // On packing failure, fall through to original call.
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
