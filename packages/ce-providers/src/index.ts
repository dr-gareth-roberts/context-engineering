export * from "./types.js";
export * from "./openai.js";
export * from "./anthropic.js";
export * from "./token-estimators.js";
export * from "./models.js";
export * from "./presets.js";
export { createLazyClient } from "./lazy-client.js";

import type { EmbeddingProvider as ProviderEmbeddingProvider } from "./types.js";
import type { EmbeddingProvider as CoreEmbeddingProvider } from "@context-engineering/core";

/**
 * Wrap a ce-providers EmbeddingProvider to match the ce-core EmbeddingProvider interface.
 * The core interface expects `embed(texts: string[]): Promise<number[][]>`,
 * while the provider interface returns `{ vectors, model }`.
 */
export function toCoreEmbeddingProvider(
  provider: ProviderEmbeddingProvider
): CoreEmbeddingProvider {
  return {
    async embed(texts: string[]): Promise<number[][]> {
      const result = await provider.embed(texts);
      return result.vectors;
    },
  };
}
