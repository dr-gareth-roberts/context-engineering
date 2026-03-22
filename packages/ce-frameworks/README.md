# @context-engineering/frameworks

Drop-in context management middleware for LangChain, LlamaIndex, and CrewAI. Automatically packs conversation messages within your model's token budget using `@context-engineering/core` — no framework-specific dependencies required.

## Quick Start

### LangChain

```ts
import { ChatOpenAI } from "@langchain/openai";
import { withContextLangChain } from "@context-engineering/frameworks";

const model = withContextLangChain(new ChatOpenAI({ model: "gpt-4o" }), {
  budget: 128_000,
  strategy: "trim",
});

// Use model.invoke() as normal — context is managed automatically
const result = await model.invoke(messages);
```

### LlamaIndex

```ts
import { OpenAI } from "llamaindex";
import { withContextLlamaIndex } from "@context-engineering/frameworks";

const llm = withContextLlamaIndex(new OpenAI({ model: "gpt-4o" }), {
  budget: 128_000,
});

const result = await llm.chat({ messages });
```

### CrewAI

```ts
import { withContextCrewAI } from "@context-engineering/frameworks";

const managedLlm = withContextCrewAI(llm, { budget: 128_000 });
const agent = new Agent({ llm: managedLlm /* ... */ });
```

### Generic (any framework)

```ts
import { withContextGeneric } from "@context-engineering/frameworks";

const wrapped = withContextGeneric(myLlm, "generate", {
  budget: 128_000,
  messageExtractor: args => args[0].messages,
  messageInjector: (args, packed) => [{ ...args[0], messages: packed }],
});
```

## How It Works

```
Your Code
  |
  v
Framework Adapter (LangChain / LlamaIndex / CrewAI / Generic)
  |  Proxy intercepts invoke/chat/call
  |
  v
Shared packMessages()
  |  1. Convert framework messages -> ContextItem[]
  |  2. Score: system=100, recent=90, older decays 50->10
  |  3. Pack via ce-core's pack() within budget
  |  4. Apply strategy (trim / summarize / custom)
  |  5. Convert ContextItem[] -> framework messages
  |
  v
Original Framework Method (with packed messages)
  |
  v
LLM API
```

Each adapter uses a Proxy to intercept the framework's main method (`invoke`, `chat`, or `call`) without modifying the original object. Messages are converted to `ContextItem[]` using duck-typing, packed within budget, then converted back preserving original message objects.

## Options

| Option               | Type                                | Default  | Description                              |
| -------------------- | ----------------------------------- | -------- | ---------------------------------------- |
| `budget`             | `number`                            | `128000` | Token budget                             |
| `reserveTokens`      | `number`                            | `4096`   | Tokens reserved for model response       |
| `strategy`           | `'trim' \| 'summarize' \| Function` | `'trim'` | How to handle dropped messages           |
| `log`                | `boolean`                           | `true`   | Log summary to console                   |
| `systemPriority`     | `number`                            | `100`    | Priority for system messages             |
| `recentMessageCount` | `number`                            | `2`      | Recent messages to protect from trimming |
| `weights`            | `ScoringWeights`                    | —        | Custom scoring weights                   |
| `on.pack`            | `Function`                          | —        | Listener for pack events                 |
| `on.trim`            | `Function`                          | —        | Listener for trim events                 |
| `on.error`           | `Function`                          | —        | Listener for errors                      |
| `recorder`           | `ContextRecorder`                   | —        | Record pack decisions for replay         |

## Design Decisions

### Duck-typing over framework imports

The adapters use interface matching (`LangChainLike`, `LlamaIndexLike`, etc.) rather than importing framework packages. This means:

- **Zero framework dependencies** — works with any version of LangChain, LlamaIndex, or CrewAI
- **No version conflicts** — your framework version is never constrained by this package
- **Works with custom subclasses** — any object matching the duck-type interface works

### Shared `packMessages()` core

All adapters delegate to a single `packMessages()` function that handles conversion, scoring, packing, strategy application, and event emission. This ensures consistent behavior across frameworks and avoids logic duplication.

### Graceful fallthrough

If context packing fails for any reason (invalid budget, unexpected message format, etc.), the adapter catches the error, emits it via the `on.error` listener, and calls the original method with unmodified messages. Your code never breaks due to the middleware.

## Integration with Other Packages

```ts
import { createContextRecorder, replay } from "@context-engineering/core";
import { withContextLangChain } from "@context-engineering/frameworks";

// Record decisions for A/B testing
const recorder = createContextRecorder();
const model = withContextLangChain(chatModel, {
  budget: 128_000,
  recorder,
});

// Later: replay with different strategies
const results = await replay(recorder.getRecordings(), {
  weights: { priority: 1, recency: 0.5 },
});
```
