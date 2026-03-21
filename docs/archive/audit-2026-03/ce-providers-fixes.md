# ce-providers Audit Fixes

**Date:** 2026-03-17
**Scope:** All issues identified in `ce-providers-audit.md`

## Files Modified

| File                           | Action                                           |
| ------------------------------ | ------------------------------------------------ |
| `src/token-estimators.ts`      | Rewritten -- C1, C2, H5                          |
| `src/lazy-client.ts`           | **New file** -- H1, H2                           |
| `src/openai.ts`                | Rewritten -- H2, H3, M4, M6, M7                  |
| `src/anthropic.ts`             | Rewritten -- H2, H3, H4, M1, M7                  |
| `src/types.ts`                 | Edited -- M5                                     |
| `src/models.ts`                | Edited -- M2                                     |
| `src/index.ts`                 | Edited -- export lazy-client                     |
| `src/token-estimators.test.ts` | Rewritten -- tests for all token-estimator fixes |
| `src/providers.test.ts`        | Rewritten -- tests for all provider fixes        |

## Fix Details

### Critical

**C1: Wrong tiktoken encoding (cl100k_base -> o200k_base)**

Changed the default encoding from `cl100k_base` to `o200k_base` in `token-estimators.ts`. All modern OpenAI models listed in `MODEL_METADATA` (GPT-4o, GPT-4.1, o-series) use `o200k_base`. Added a `CL100K_MODELS` set for the older models (GPT-4, GPT-3.5) and a `getEncodingForModel()` function that selects the correct encoding based on the model name. Both encodings are cached independently.

**C2: Token estimators ignoring options parameter**

Both `openaiTokenEstimator` and `anthropicTokenEstimator` now accept the full `options?: { model?: string; provider?: string }` parameter matching the `TokenEstimator` interface from `ce-core`. The OpenAI estimator uses `options.model` to select between `o200k_base` and `cl100k_base` encodings. The Anthropic estimator accepts and ignores the parameter (prefix `_options`) since it uses a heuristic that doesn't vary by model.

### High

**H1: Lazy getClient caching rejected promise forever**

Created `src/lazy-client.ts` with a `createLazyClient<T>()` generic helper. The `.catch()` handler clears `pending = null` on rejection, so the next call to the returned function will invoke the factory again instead of returning the cached rejected promise.

**H2: Duplicate getClient pattern (3 copies)**

All three classes (`OpenAIProvider`, `OpenAIEmbeddingProvider`, `AnthropicProvider`) now use `createLazyClient()`. The OpenAI providers share a `createOpenAIClient()` factory function. The `AnthropicProvider` calls `createLazyClient()` inline in the constructor. The `private client` and `private clientPromise` fields are gone; replaced by a single `private getClient: () => Promise<T>` function property.

**H3: No validation of empty messages array**

Both `OpenAIProvider.generate()` and `AnthropicProvider.generate()` now throw `"At least one message is required"` before any API call when given an empty array.

**H4: No validation of all-system messages for Anthropic**

`AnthropicProvider.generate()` now throws `"At least one non-system message is required for the Anthropic API"` when all messages have `role: "system"` and the filtered `anthropicMessages` array is empty. This check runs after system-message extraction and before the API call.

**H5: openaiTokenEstimator crashes on null/undefined**

Added `if (!text) return 0;` as the first line of `openaiTokenEstimator`. This handles `null`, `undefined`, and empty string, matching the behavior of `anthropicTokenEstimator`. Also added `if (!text) return 0;` to `anthropicTokenEstimator` before the `.trim()` call, so it no longer relies on `.trim()` not crashing on falsy input.

### Medium

**M1: Stale Anthropic default model**

Changed `DEFAULT_MODEL` in `anthropic.ts` from `"claude-3-5-sonnet-20241022"` to `"claude-sonnet-4-6"`.

**M2: MODEL_METADATA key mismatch with MODEL_PRICING**

Changed `"claude-haiku-4-5-20251001"` to `"claude-haiku-4-5"` in `models.ts` to match the key used in `ce-core/cost.ts`'s `MODEL_PRICING`. Added a JSDoc comment noting the alignment.

**M4: EmbeddingOptions not used by OpenAIEmbeddingProvider**

Changed `embed()` parameter type from inline `{ model?: string }` to the imported `EmbeddingOptions` interface from `types.ts`.

**M5: LLMMessage.role type too narrow**

Changed the `role` type from `"system" | "user" | "assistant"` to `"system" | "user" | "assistant" | "tool" | (string & {})`. The `(string & {})` pattern preserves IDE autocomplete for the known literal values while accepting any string at runtime (e.g., `"function"` or future roles).

**M6: Deprecated max_tokens for newer OpenAI models**

Added a `USES_MAX_COMPLETION_TOKENS` set in `openai.ts` listing o-series and GPT-4.1 models. `generate()` now sends `max_completion_tokens` for these models and `max_tokens` for older models (GPT-4o, GPT-4o-mini). When `maxTokens` is not provided, neither parameter is sent.

**M7: Undefined temperature passed explicitly**

Both providers now use conditional parameter building. Temperature is only added to the params object when `options.temperature !== undefined`. For OpenAI, `max_tokens`/`max_completion_tokens` is similarly only included when `options.maxTokens !== undefined`. This avoids sending `temperature: undefined` or `max_tokens: undefined` to the API.

## Test Changes

### `token-estimators.test.ts`

- Added null/undefined input tests for both estimators (H5)
- Added test verifying o200k_base is used by default (C1)
- Added test verifying cl100k_base is used for older models (C1)
- Added test that options parameter is accepted without model (C2)
- Added unicode/emoji input test (L5 from audit)

### `providers.test.ts`

- Added `createLazyClient` test suite: single factory call, identity, concurrency deduplication, retry after rejection (H1, H2)
- Added empty-messages rejection tests for OpenAI and Anthropic (H3)
- Added all-system-messages rejection test for Anthropic (H4)
- Added `max_completion_tokens` tests for GPT-4.1 and o3 (M6)
- Added `max_tokens` test scoped to non-reasoning model `gpt-4o` (M6)
- Added temperature-omission tests for both providers (M7)
- Added `claude-haiku-4-5` key alignment test for MODEL_METADATA (M2)
- Updated mock model names in Anthropic tests to use `claude-sonnet-4-6` (M1)
- Replaced `(provider as any).client = ...` pattern with `injectClient()` helper that overrides `getClient` function property (L3 improvement)

## Issues NOT Fixed (by design)

| ID  | Reason                                                                                            |
| --- | ------------------------------------------------------------------------------------------------- |
| L1  | No Anthropic embedding API exists; adding a stub would be misleading                              |
| L2  | Module-level encoding cache is intentional for performance; now caches two encodings              |
| L4  | Testing the actual dynamic `import()` requires integration tests with/without peer deps installed |
| L6  | Anthropic SDK reads `ANTHROPIC_BASE_URL` from env automatically; explicit read would be redundant |
| N1  | Renaming `maxTokens` to `contextWindow` would be a breaking change for `as const` consumers       |
| N3  | Retry/backoff is a cross-cutting concern better handled at the application layer                  |
| N4  | Streaming requires a new interface shape; out of scope for a bug-fix pass                         |
| N5  | The 200k value is the standard tier; 1M is the same model ID but a different tier                 |
