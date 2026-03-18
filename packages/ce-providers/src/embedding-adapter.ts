import type { EmbeddingProvider as CoreEmbeddingProvider } from "@context-engineering/core";
import type { EmbeddingProvider as ProvidersEmbeddingProvider } from "./types.js";

/**
 * Adapt a ce-providers EmbeddingProvider to the ce-core EmbeddingProvider interface.
 *
 * The ce-providers EmbeddingProvider returns `{ vectors, model }` while ce-core
 * expects a plain `number[][]`. This adapter bridges the two.
 */
export function adaptEmbeddingProvider(
  provider: ProvidersEmbeddingProvider
): CoreEmbeddingProvider {
  return {
    embed: async (texts: string[]) => {
      const result = await provider.embed(texts);
      return result.vectors;
    },
  };
}
