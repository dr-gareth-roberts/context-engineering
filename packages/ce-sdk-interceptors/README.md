# @context-engineering/sdk-interceptors

Drop-in context management for OpenAI and Anthropic SDKs — wrap your client and conversations are automatically packed within the model's token budget.

## How It Works

The interceptor wraps your SDK client with a proxy that intercepts API calls (`chat.completions.create` for OpenAI, `messages.create` for Anthropic). Before each call, it converts messages to `ContextItem[]`, packs them within the model's context window using ce-core, and replaces the messages array with the packed result. If everything fits, it passes through unchanged.

## Quick Start

### OpenAI

```typescript
import OpenAI from "openai";
import { withContext } from "@context-engineering/sdk-interceptors";

const client = withContext(new OpenAI(), {
  strategy: "summarize",
  recentMessageCount: 4,
  on: {
    trim: event => console.log(`Trimmed ${event.trimmedMessages} messages`),
  },
});

// Use normally — context is managed automatically
const response = await client.chat.completions.create({
  model: "gpt-4.1",
  messages: longConversation, // can exceed context window
});
```

### Anthropic

```typescript
import Anthropic from "@anthropic-ai/sdk";
import { withContextAnthropic } from "@context-engineering/sdk-interceptors";

const client = withContextAnthropic(new Anthropic(), {
  strategy: "trim",
  reserveTokens: 8192,
});

const response = await client.messages.create({
  model: "claude-sonnet-4-6",
  system: "You are a helpful assistant.",
  messages: longConversation,
  max_tokens: 4096,
});
```

## Strategies

| Strategy    | Behavior                                                                        |
| ----------- | ------------------------------------------------------------------------------- |
| `trim`      | Drop lowest-scored older messages. System prompt and recent messages protected. |
| `summarize` | Replace dropped messages with a bullet-point digest.                            |
| Custom `fn` | Pass a `SummarizeFunction` for LLM-powered or custom summarisation.             |

## API Reference

### `withContext(client, options?): client`

Wraps an OpenAI client. Intercepts `client.chat.completions.create()`.

### `withContextAnthropic(client, options?): client`

Wraps an Anthropic client. Intercepts `client.messages.create()`. Handles the Anthropic-specific separation of system prompt from messages.

### `InterceptorOptions`

| Option               | Type                   | Default  | Description                                      |
| -------------------- | ---------------------- | -------- | ------------------------------------------------ |
| `budget`             | `number`               | auto     | Token budget override (auto-detected from model) |
| `reserveTokens`      | `number`               | `4096`   | Tokens reserved for model response               |
| `strategy`           | `ContextStrategy`      | `'trim'` | How to handle overflow                           |
| `log`                | `boolean`              | `true`   | Log a one-line summary after each call           |
| `systemPriority`     | `number`               | `100`    | Priority for system messages (never trimmed)     |
| `recentMessageCount` | `number`               | `2`      | Recent messages protected from trimming          |
| `includePack`        | `boolean`              | `false`  | Include full `ContextPack` in events             |
| `recorder`           | `ContextRecorder`      | —        | Record decisions for replay/A-B testing          |
| `on.pack`            | `ContextEventListener` | —        | Called after packing                             |
| `on.trim`            | `ContextEventListener` | —        | Called when messages are trimmed                 |
| `on.error`           | `(error) => void`      | —        | Called on packing errors (falls through)         |

### `ContextEvent`

| Field             | Type      | Description                    |
| ----------------- | --------- | ------------------------------ |
| `model`           | `string`  | Model used                     |
| `totalMessages`   | `number`  | Messages before packing        |
| `keptMessages`    | `number`  | Messages after packing         |
| `trimmedMessages` | `number`  | Messages dropped               |
| `summarized`      | `boolean` | Whether a summary was injected |
| `tokensUsed`      | `number`  | Tokens after packing           |
| `tokenBudget`     | `number`  | Total model budget             |
| `utilization`     | `number`  | Utilisation percentage (0-100) |
| `packTimeMs`      | `number`  | Time taken to pack             |

## Message Scoring

Messages are converted to `ContextItem[]` with this priority scheme:

- **System messages**: priority `100` (always kept)
- **Recent N messages**: priority `90` (protected from trimming)
- **Older messages**: priority decays from `50` to `10` based on position

Recency is normalised 0-1 across the conversation. The system prompt and most recent turns are always preserved, while older middle-of-conversation messages are candidates for trimming.

## Design Decisions

**Why a Proxy-based wrapper instead of middleware?** Proxies are transparent — the wrapped client keeps the same call surface as the original. No new abstractions to learn, no middleware registration, no request/response pipeline to understand. You swap one line of client initialisation and everything else stays the same. (See _Limitations_ below for the one place the surface differs: the helper methods exposed on the object returned by `create()`.)

**Why fall through on packing errors?** If packing fails (malformed messages, unexpected types), the interceptor forwards the original request unchanged rather than throwing. This makes the interceptor safe to add to production code — the worst case is that packing doesn't happen, not that your API call fails.

**Why auto-detect model budget?** The interceptor uses `MODEL_METADATA` from ce-providers to look up context window sizes. This means you don't need to track context limits per model — just set `reserveTokens` for the response and the interceptor handles the rest. Unknown models default to 128k.

## Integration with Other Packages

### ce-core

Messages are converted to `ContextItem[]` and packed via `pack()`. The interceptor is a thin adapter layer between SDK message formats and ce-core's packing engine.

### ce-providers

Model metadata (context window sizes) comes from `MODEL_METADATA` in ce-providers, enabling automatic budget detection per model.

### ce-core (recorder)

Pass a `ContextRecorder` to capture every packing decision. Use `replay()` from ce-core to A/B test different strategies against recorded production traffic.

## Limitations

### `create()` returns a forwarding thenable, not the raw SDK `APIPromise`

The OpenAI and Anthropic SDKs return a custom `APIPromise` from `create()`. It
is awaitable like a normal `Promise`, but also exposes helper methods on top of
the thenable. The wrapped `create()` cannot return the raw `APIPromise`
synchronously, because packing is asynchronous and must finish before the real
request is issued. Instead it returns a forwarding thenable that:

- **awaits to the same value** — `await client.chat.completions.create(params)`
  yields the response body, and `for await (...)` over a streaming call yields
  the `Stream`, exactly as with the unwrapped client.
- **forwards the public helpers** `.withResponse()` and `.asResponse()`, so the
  documented pattern for reading rate-limit headers and request IDs still works:

  ```typescript
  const { data, response } = await client.chat.completions
    .create(params)
    .withResponse();
  ```

- **does not forward private members** (`.parse()`, `._thenUnwrap`, and any other
  internal APIPromise members). These are not part of the SDK's public contract.
  Callers who need them must use the unwrapped client.

Because the forwarded set is tied to the SDK's public `APIPromise` surface, it is
SDK-version-coupled: if a future SDK release adds a new public helper, it must be
added here too.

## License

MIT
