# ce-providers Deep Audit

**Date:** 2026-03-17
**Scope:** `packages/ce-providers/src/` -- all 7 source files and 3 test files
**Auditor:** Claude Opus 4.6 (automated)

## Summary

The `ce-providers` package is compact (7 source files, ~250 LOC) and structurally sound. The lazy-loading pattern for optional peer dependencies is well-designed. However, there is one **critical** bug (wrong tiktoken encoding for modern models), several **high** priority issues (race condition in lazy init, missing input validation, no empty-messages guard), and a handful of medium/low items around dead types, stale defaults, and testing gaps.

**Issue counts:** 2 Critical, 5 High, 7 Medium, 6 Low, 5 Notes

---

## Critical Issues

### C1. Wrong tiktoken encoding for GPT-4o / GPT-4.1 / o-series models

**File:** `src/token-estimators.ts:8`
**Severity:** CRITICAL

```ts
cachedEncoding = getEncoding("cl100k_base");
```

`cl100k_base` is the encoding for GPT-3.5 and GPT-4 (non-o). All models this toolkit actually targets -- GPT-4o, GPT-4o-mini, GPT-4.1, GPT-4.1-mini, GPT-4.1-nano, o1, o3, o4-mini -- use the `o200k_base` encoding. Using the wrong encoding produces **systematically wrong token counts** for every estimation call. The error magnitude varies by content but can be 5-15% off, which is significant for budget-constrained packing.

**Impact:** Every user calling `openaiTokenEstimator` or `presets.openai.estimator` gets incorrect token counts for all currently-listed OpenAI models. This silently causes packs to over-fill or under-fill budgets.

**Fix:** Change to `o200k_base`, or better, accept a model parameter and select the encoding dynamically:

```ts
// Minimal fix:
cachedEncoding = getEncoding("o200k_base");

// Better fix: support both encodings with model-aware selection
```

The README also claims "Exact for GPT models" which is false when using the wrong encoding.

---

### C2. `openaiTokenEstimator` ignores the `options` parameter from `TokenEstimator` interface

**File:** `src/token-estimators.ts:6`
**Severity:** CRITICAL

The `TokenEstimator` interface in `ce-core` is:

```ts
interface TokenEstimator {
  (text: string, options?: { model?: string; provider?: string }): number;
}
```

But the implementation ignores the `options` parameter entirely:

```ts
export const openaiTokenEstimator: TokenEstimator = (text: string) => {
```

This means even if a caller passes `{ model: "gpt-3.5-turbo" }`, the estimator always uses a single cached encoding. Combined with C1, there is no way for a caller to get correct estimates for cl100k models (GPT-4-turbo, GPT-3.5) vs o200k models (GPT-4o, GPT-4.1) -- the estimator is hardcoded to one encoding.

**Fix:** Accept the options parameter, inspect `options.model`, and select the appropriate encoding:

```ts
const cl100kModels = new Set(["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]);
// Use cl100k_base for those, o200k_base for everything else
```

Similarly, `anthropicTokenEstimator` ignores the options parameter, though this matters less since it's a heuristic anyway.

---

## High Priority

### H1. Race condition in lazy client initialization

**Files:** `src/openai.ts:29-43`, `src/openai.ts:84-98`, `src/anthropic.ts:25-40`
**Severity:** HIGH

The `getClient()` pattern has a race condition. If two concurrent calls hit `getClient()` simultaneously:

1. Call A checks `this.client` -- null
2. Call A checks `this.clientPromise` -- null
3. Call A starts `this.clientPromise = import("openai").then(...)`
4. Call B checks `this.client` -- still null (import hasn't resolved)
5. Call B checks `this.clientPromise` -- now set, so it awaits it
6. Both resolve, but the `.then()` callback does `this.client = client`

This specific pattern actually works correctly for the race between calls A and B because they share the same promise. However, there is a subtler issue: if the `import()` rejects (e.g., the peer dependency isn't installed), `this.clientPromise` is set to a rejected promise, and **all subsequent calls will also reject** with the cached rejected promise -- even if the module becomes available later (unlikely but possible in testing scenarios). There is no retry mechanism and no error wrapping.

**Fix:** Clear `this.clientPromise` on rejection:

```ts
this.clientPromise = import("openai")
  .then(({ default: OpenAIClient }) => {
    // ...
  })
  .catch(err => {
    this.clientPromise = null;
    throw err;
  });
```

### H2. Duplicate `getClient()` implementation across three classes

**Files:** `src/openai.ts:29-43`, `src/openai.ts:84-98`, `src/anthropic.ts:25-40`
**Severity:** HIGH (maintainability)

The lazy-loading `getClient()` pattern is copy-pasted three times with minor variations (different SDK import, different env vars). This violates DRY and makes it easy for fixes (like H1) to be applied inconsistently.

**Fix:** Extract a generic `createLazyClient<T>()` helper:

```ts
function createLazyClient<T>(factory: () => Promise<T>): () => Promise<T> {
  let client: T | null = null;
  let pending: Promise<T> | null = null;
  return () => {
    if (client) return Promise.resolve(client);
    if (!pending) {
      pending = factory()
        .then(c => {
          client = c;
          return c;
        })
        .catch(err => {
          pending = null;
          throw err;
        });
    }
    return pending;
  };
}
```

### H3. No validation of empty messages array

**Files:** `src/openai.ts:45-72`, `src/anthropic.ts:42-82`
**Severity:** HIGH

Both `generate()` methods accept `messages: LLMMessage[]` but never validate the array is non-empty. Passing `[]` will:

- **OpenAI:** Send an empty messages array to the API, which returns a 400 error with an unhelpful message
- **Anthropic:** Send an empty messages array after filtering out system messages, which also returns a 400 error

**Fix:** Add a guard at the top of `generate()`:

```ts
if (!messages.length) {
  throw new Error("At least one message is required");
}
```

### H4. Anthropic provider does not validate that non-system messages exist

**File:** `src/anthropic.ts:49-53`
**Severity:** HIGH

If all messages are `system` role, `anthropicMessages` will be an empty array. The Anthropic API requires at least one `user` message. The current code would send `{ messages: [], system: "..." }` which will fail with an opaque API error.

```ts
const anthropicMessages = messages
  .filter(msg => msg.role !== "system")
  .map(msg => ({ ... }));
// anthropicMessages could be [] here -- no check
```

### H5. `openaiTokenEstimator` crashes on `null`/`undefined` input; `anthropicTokenEstimator` does not

**File:** `src/token-estimators.ts:6-11`
**Severity:** HIGH

`openaiTokenEstimator` calls `cachedEncoding.encode(text)` directly. If `text` is `null` or `undefined` (which can happen in JS despite TS types), this will throw an opaque error from the tiktoken WASM module.

By contrast, `anthropicTokenEstimator` handles this gracefully via `text.trim()` and the emptiness check.

The core's `estimateTokens()` guards against `null` (`if (text == null) return 0`), but direct callers of `openaiTokenEstimator` get no protection.

**Fix:** Add a null/empty guard to `openaiTokenEstimator`:

```ts
export const openaiTokenEstimator: TokenEstimator = (text: string) => {
  if (!text) return 0;
  // ...
};
```

---

## Medium Priority

### M1. Stale default model for Anthropic

**File:** `src/anthropic.ts:9`
**Severity:** MEDIUM

```ts
const DEFAULT_MODEL = "claude-3-5-sonnet-20241022";
```

This is a dated model. The `models.ts` file already lists `claude-sonnet-4-6` as a known model. The default should be updated to `claude-sonnet-4-6` (or `claude-sonnet-4-5-20250514` at minimum) to match current best practices.

### M2. `MODEL_METADATA` is disconnected from `MODEL_PRICING` in ce-core

**Files:** `src/models.ts`, `packages/ce-core/src/cost.ts`
**Severity:** MEDIUM

`ce-providers/models.ts` defines `MODEL_METADATA` with context window sizes. `ce-core/cost.ts` defines `MODEL_PRICING` with pricing data. These are two separate, unrelated maps for the same set of models. They are out of sync:

- `MODEL_METADATA` has `claude-haiku-4-5-20251001` but `MODEL_PRICING` has `claude-haiku-4-5` (different keys)
- `MODEL_METADATA` has `o1-mini` but `MODEL_PRICING` does not
- `MODEL_METADATA` has `gpt-4.1-nano` but `MODEL_PRICING` does not
- `MODEL_METADATA` has `gpt-4o-mini` but `MODEL_PRICING` does not

This makes it confusing for users who might expect to look up both metadata and pricing for the same model key.

### M3. `MODEL_METADATA` uses `as const` but has no typed accessor

**File:** `src/models.ts`
**Severity:** MEDIUM

The `as const` assertion makes the type very specific, but there is no helper function to look up a model or validate a model string. Users must use string literal types that exactly match the keys. A helper like `getModelMetadata(provider, model)` with proper error messages would be more ergonomic.

### M4. `EmbeddingOptions` type is defined but never imported by `OpenAIEmbeddingProvider`

**File:** `src/openai.ts:100-103`
**Severity:** MEDIUM

The `embed()` method defines its options inline as `{ model?: string }` instead of using the `EmbeddingOptions` interface from `types.ts`. While the shape currently matches, this defeats the purpose of having a shared interface.

```ts
// Current (inline type):
async embed(inputs: string[] | string, options: { model?: string } = {})

// Should be:
async embed(inputs: string[] | string, options: EmbeddingOptions = {})
```

### M5. `LLMMessage.role` type is too narrow

**File:** `src/types.ts:2`
**Severity:** MEDIUM

```ts
role: "system" | "user" | "assistant";
```

This excludes:

- OpenAI's `"tool"` and `"function"` roles
- Anthropic's tool-use patterns (though those use content blocks)

Users who want to send tool results cannot use this interface. Consider adding `"tool"` at minimum, or using `string` with the three core roles as the common case.

### M6. `OpenAIProvider.generate` sends `max_tokens` but newer OpenAI models require `max_completion_tokens`

**File:** `src/openai.ts:53`
**Severity:** MEDIUM

```ts
max_tokens: options.maxTokens,
```

OpenAI deprecated `max_tokens` in favor of `max_completion_tokens` for newer models (o1, o3, o4-mini, GPT-4.1). The `max_tokens` parameter still works for older models (GPT-4o, GPT-4o-mini) but the OpenAI SDK may emit deprecation warnings. For o-series models, `max_tokens` is ignored entirely in some configurations.

### M7. `temperature` is passed as `undefined` when not provided, which may differ from omitting it

**Files:** `src/openai.ts:54`, `src/anthropic.ts:59`
**Severity:** MEDIUM

```ts
temperature: options.temperature,  // undefined if not set
```

Passing `temperature: undefined` to the API client is not the same as omitting the key. Most SDK clients strip `undefined` values, but this is an implementation detail. Explicitly only including `temperature` when defined would be more robust:

```ts
...(options.temperature !== undefined && { temperature: options.temperature }),
```

---

## Low Priority

### L1. No Anthropic embedding provider

**Severity:** LOW

There is no `AnthropicEmbeddingProvider` class. Anthropic does not offer a first-party embedding API, so this is technically correct. However, a note in the types or README explaining this asymmetry would be helpful.

### L2. `openaiTokenEstimator` caches a single encoding in module scope

**File:** `src/token-estimators.ts:4`
**Severity:** LOW

```ts
let cachedEncoding: Tiktoken | null = null;
```

This module-level singleton means:

1. The encoding is never freed (minor memory concern for long-running processes)
2. There is no way to use different encodings for different models (related to C1/C2)
3. In test environments, the cached state leaks between test files

### L3. Test files use `(provider as any).client = ...` pattern extensively

**File:** `src/providers.test.ts` (lines 18, 53, 78, 96, 114, 139, 165, 171, 194, 211, 231, 253, 277, 297, 319, 347, 359, 364, 375)
**Severity:** LOW

Every test accesses `private` members via `as any` to inject mock clients. This is brittle -- if the internal field name changes, all tests silently break at runtime rather than at compile time. A better approach would be to accept an injected client in the constructor:

```ts
constructor(options: OpenAIProviderOptions & { _client?: OpenAI } = {}) {
  if (options._client) this.client = options._client;
}
```

Or use dependency injection more formally.

### L4. No test for `getClient()` lazy loading / dynamic import path

**File:** `src/providers.test.ts`
**Severity:** LOW

All tests bypass `getClient()` by injecting a mock client directly. The actual lazy `import()` path -- which is the most failure-prone part (peer dep not installed, import error, etc.) -- is never tested.

### L5. No test for `openaiTokenEstimator` with non-ASCII / unicode / emoji input

**File:** `src/token-estimators.test.ts`
**Severity:** LOW

The core package tests emoji input (`defaultTokenEstimator("\u{1F389}\u{1F389}\u{1F389}")`), but the providers test file does not test `openaiTokenEstimator` with emoji, CJK characters, or mixed scripts. Tiktoken behavior with these inputs can be surprising.

### L6. `AnthropicProvider` does not read `ANTHROPIC_BASE_URL` env var

**File:** `src/anthropic.ts:32`
**Severity:** LOW

```ts
baseURL: this.options.baseURL,
// Compare to OpenAI:
baseURL: this.options.baseURL ?? process.env.OPENAI_BASE_URL,
```

The Anthropic SDK reads `ANTHROPIC_BASE_URL` from env automatically, so this is not a bug per se, but it is inconsistent with the OpenAI provider which explicitly reads from env. The Python SDK in this same repo does read `ANTHROPIC_BASE_URL`. If the Anthropic SDK ever changes its env var behavior, this would break silently.

---

## Notes & Questions

### N1. `maxTokens` in `MODEL_METADATA` likely means context window, not output limit

The field name `maxTokens` is ambiguous. For OpenAI models, the context window and output limit are different (e.g., GPT-4o has 128k context but 16k max output). The values stored (128000, 200000, 1048576) are context windows, but a naive reader might interpret `maxTokens` as the max output tokens. Consider renaming to `contextWindow` or `maxContextTokens`.

### N2. `gpt-4o-mini` as the OpenAI default is a reasonable cost-conscious choice

No issue here, just noting this is intentional.

### N3. The package has no retry/backoff logic

Both providers propagate API errors directly. In a production context engineering workflow, transient rate limits (429) and server errors (500, 503) are common. Consider either adding retry logic or documenting that callers should handle retries.

### N4. No streaming support

The `generate()` method returns a full `LLMResult`. There is no streaming variant. The core package has `packStream()` for async iteration, but the providers don't support streaming responses. This is worth noting in the README.

### N5. Claude Opus 4.6 has a 1M context window but `MODEL_METADATA` says 200000

**File:** `src/models.ts:15`

```ts
"claude-opus-4-6": { maxTokens: 200000 },
```

Claude Opus 4.6 (the model powering this audit) supports up to 1M tokens in context. The `MODEL_METADATA` lists 200k which is the standard tier. The 1M context version is the same model ID. This may need a note or a separate entry.

---

## Good Patterns

1. **Lazy dynamic imports for optional peer deps** -- The `import("openai").then(...)` pattern is the correct way to handle optional peer dependencies in Node.js. It avoids crashing at module load time when the SDK isn't installed.

2. **`as const` on MODEL_METADATA** -- Provides excellent type inference for consumers who want to access specific model properties.

3. **`satisfies` in presets.ts** -- Using `satisfies ProviderPreset` checks the shape without widening the type. Good modern TypeScript.

4. **Clean separation of concerns** -- Types, models, estimators, presets, and providers are in separate files with clear responsibilities.

5. **System message extraction in Anthropic provider** -- Correctly handles the OpenAI-to-Anthropic message format translation, including joining multiple system messages.

6. **Non-text block handling** -- The Anthropic provider correctly handles `tool_use` blocks by checking for `"text" in block` rather than assuming all blocks have text.

7. **Usage normalization** -- Both providers normalize provider-specific usage fields (`prompt_tokens` / `input_tokens`) into a consistent `LLMUsage` shape.

8. **Peer dependency metadata** -- `peerDependenciesMeta` with `optional: true` correctly signals that neither SDK is required at install time.

---

## File-by-File Detail

### `src/types.ts` (46 lines)

Clean interface definitions. Issues: M5 (role type too narrow), M4 (EmbeddingOptions defined but not used by embed impl).

No dead code. All exports are consumed by other files in the package or by downstream packages.

### `src/models.ts` (21 lines)

Static metadata. Issues: M2 (key mismatch with cost.ts), N1 (ambiguous field name), N5 (Opus context window).

No logic to audit. The `as const` assertion is correct.

### `src/token-estimators.ts` (18 lines)

The core of the package. Issues: **C1** (wrong encoding), **C2** (ignores options), **H5** (no null guard on openai estimator), L2 (singleton cache).

The `anthropicTokenEstimator` is correctly implemented for what it claims to do (heuristic estimation). The `Math.max(1, ...)` guard and trim + emptiness check are correct.

### `src/presets.ts` (31 lines)

Thin wrapper. No issues beyond those inherited from the estimators. Good JSDoc example.

### `src/openai.ts` (116 lines)

Provider implementations. Issues: **H1** (race/retry on import failure), H2 (duplicate getClient), H3 (no empty messages check), M6 (max_tokens deprecated), M7 (undefined temperature), L3 (testability).

Line 57: `response.choices[0]` -- correctly guarded by the `?.` on line 58, so empty choices returns `""`. This is correct behavior.

Line 104: `Array.isArray(inputs) ? inputs : [inputs]` -- correct normalization.

### `src/anthropic.ts` (83 lines)

Provider implementation. Issues: **H1** (race/retry), H2 (duplicate getClient), H3/H4 (no message validation), M1 (stale default), M7 (undefined temperature), L6 (no ANTHROPIC_BASE_URL env read).

Line 47-48: System message extraction is correct. `filter` + `map` + `join("\n\n")` handles 0, 1, and N system messages properly.

Line 60: `system: system || undefined` -- converts empty string to undefined, which is correct (Anthropic API rejects `system: ""`).

Line 64-66: Content block text extraction using `"text" in block` is correct and handles tool_use blocks.

Lines 68-75: The `response.usage` conditional is technically wrong -- Anthropic **always** returns `usage` on a successful response (it's not optional in the API). The conditional is harmless but misleading. The manual `totalTokens` calculation (line 72-73) is correct since Anthropic doesn't return a total field.

### `src/index.ts` (6 lines)

Barrel file. Re-exports everything. No issues. All exports are correctly using `.js` extensions for ESM.

### `src/token-estimators.test.ts` (53 lines)

Good coverage of basic cases. Missing: unicode/emoji tests (L5), null/undefined tests for openai estimator, tests with the options parameter.

### `src/presets.test.ts` (20 lines)

Minimal but correct. Validates identity (not just equality) of estimator references via `toBe`.

### `src/providers.test.ts` (418 lines)

Thorough mock-based tests covering happy paths, edge cases (empty choices, missing usage, non-text blocks), and error propagation. Issues: L3 (brittle `as any` mocking), L4 (no lazy-import tests).

Missing test scenarios:

- Concurrent `generate()` calls (race condition from H1)
- Empty messages array (H3)
- All-system-messages array (H4)
- Custom model/temperature combinations with `undefined` values
- `OpenAIEmbeddingProvider` with empty string array input
