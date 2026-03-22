import type { ContextItem } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import { computeInformationGain } from "./information-gain.js";
import type {
  RetrieverConfig,
  RetrieveOptions,
  RetrievedPack,
  ContextAwareRetriever,
  VectorResult,
} from "./types.js";

/**
 * Convert a vector store result into a ContextItem with RAG metadata.
 */
function toContextItem(result: VectorResult): ContextItem {
  return {
    id: result.id,
    content: result.content,
    metadata: {
      ...(result.metadata ?? {}),
      source: "rag",
      vectorScore: result.score,
    },
  };
}

/**
 * Greedily fill a budget with the highest-gain items.
 * Stops when the next item would exceed the available token capacity.
 */
function fillWithinBudget(
  items: Array<{ item: ContextItem; gain: number }>,
  maxTokens: number,
  reserveTokens: number
): { selected: ContextItem[]; totalGain: number; tokensUsed: number } {
  const capacity = maxTokens - reserveTokens;
  const selected: ContextItem[] = [];
  let totalGain = 0;
  let tokensUsed = 0;

  for (const { item, gain } of items) {
    const tokens = estimateTokens(item.content);
    if (tokensUsed + tokens > capacity) continue;

    selected.push(item);
    totalGain += gain;
    tokensUsed += tokens;
  }

  return { selected, totalGain, tokensUsed };
}

/**
 * Create a context-aware retriever that filters out redundant chunks.
 *
 * Candidates from the vector store are scored for information gain
 * against the current context, ensuring only genuinely new information
 * makes it into the context window.
 */
export function createContextAwareRetriever(
  config: RetrieverConfig
): ContextAwareRetriever {
  return {
    async retrieve(
      query: string,
      options?: RetrieveOptions
    ): Promise<RetrievedPack> {
      const topK = options?.topK ?? 10;
      const maxCandidates = config.maxCandidates ?? topK * 3;
      const minGain = options?.minGain ?? 0.1;

      // Fetch raw candidates from the vector store
      const rawResults = await config.store.query(query, maxCandidates);
      const candidates = rawResults.map(toContextItem);

      // Score each candidate for information gain
      const scored: Array<{ item: ContextItem; gain: number }> = [];
      let filtered = 0;

      for (const candidate of candidates) {
        const { gain } = computeInformationGain(
          candidate,
          config.currentContext,
          { queryContext: options?.query }
        );

        if (gain >= minGain) {
          scored.push({ item: candidate, gain });
        } else {
          filtered++;
        }
      }

      // Sort by gain descending — highest novelty+relevance first
      scored.sort((a, b) => b.gain - a.gain);

      // Greedily fill within budget
      const { selected, totalGain, tokensUsed } = fillWithinBudget(
        scored,
        config.budget.maxTokens,
        config.budget.reserveTokens ?? 0
      );

      return {
        items: selected,
        totalGain,
        candidatesEvaluated: candidates.length,
        candidatesFiltered: filtered,
        tokensUsed,
      };
    },
  };
}
