import { estimateTokens, createBM25Index } from "@context-engineering/core";
import { computeInformationGain } from "./information-gain.js";
import type {
  HybridRetrieverConfig,
  RetrieveOptions,
  RetrievedPack,
  ContextAwareRetriever,
  VectorResult,
} from "./types.js";
import type { ContextItem } from "@context-engineering/core";

const DEFAULT_BM25_WEIGHT = 0.4;
const DEFAULT_VECTOR_WEIGHT = 0.6;
const RRF_K = 60;

/**
 * Reciprocal Rank Fusion score for a single candidate.
 * RRF = vectorWeight * 1/(k + vectorRank) + bm25Weight * 1/(k + bm25Rank)
 */
function computeRRFScore(
  vectorRank: number,
  bm25Rank: number,
  vectorWeight: number,
  bm25Weight: number
): number {
  return (
    vectorWeight * (1 / (RRF_K + vectorRank)) +
    bm25Weight * (1 / (RRF_K + bm25Rank))
  );
}

/**
 * Convert a vector result to a ContextItem with RAG metadata.
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
 * Create a hybrid retriever that fuses vector similarity and BM25 keyword
 * rankings using Reciprocal Rank Fusion, then applies information gain
 * filtering against the current context.
 */
export function createHybridRetriever(
  config: HybridRetrieverConfig
): ContextAwareRetriever {
  const bm25Weight = config.bm25Weight ?? DEFAULT_BM25_WEIGHT;
  const vectorWeight = config.vectorWeight ?? DEFAULT_VECTOR_WEIGHT;

  return {
    async retrieve(
      query: string,
      options?: RetrieveOptions
    ): Promise<RetrievedPack> {
      const topK = options?.topK ?? 10;
      const maxCandidates = config.maxCandidates ?? topK * 3;
      const minGain = options?.minGain ?? 0.1;

      // Get vector results
      const rawResults = await config.store.query(query, maxCandidates);
      if (rawResults.length === 0) {
        return {
          items: [],
          totalGain: 0,
          candidatesEvaluated: 0,
          candidatesFiltered: 0,
          tokensUsed: 0,
        };
      }

      const candidates = rawResults.map(toContextItem);

      // Build BM25 index from candidates for keyword scoring
      const bm25Index = createBM25Index();
      for (const candidate of candidates) {
        bm25Index.add(candidate.id, candidate.content);
      }

      // Rank by vector score (raw results are already sorted by vector similarity)
      const vectorRanks = new Map<string, number>();
      for (let i = 0; i < rawResults.length; i++) {
        vectorRanks.set(rawResults[i].id, i + 1);
      }

      // Rank by BM25 score
      const bm25Scores = bm25Index.scoreAll(query);
      const bm25Sorted = [...bm25Scores.entries()].sort((a, b) => b[1] - a[1]);
      const bm25Ranks = new Map<string, number>();
      for (let i = 0; i < bm25Sorted.length; i++) {
        bm25Ranks.set(bm25Sorted[i][0], i + 1);
      }

      // Compute RRF for each candidate
      const rrfScored = candidates.map(candidate => {
        const vRank = vectorRanks.get(candidate.id) ?? candidates.length + 1;
        const bRank = bm25Ranks.get(candidate.id) ?? candidates.length + 1;
        const rrf = computeRRFScore(vRank, bRank, vectorWeight, bm25Weight);
        return { candidate, rrf };
      });

      // Sort by RRF descending
      rrfScored.sort((a, b) => b.rrf - a.rrf);

      // Apply information gain filter
      const scored: Array<{ item: ContextItem; gain: number }> = [];
      let filtered = 0;

      for (const { candidate } of rrfScored) {
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

      // Fill within budget
      const capacity =
        config.budget.maxTokens - (config.budget.reserveTokens ?? 0);
      const selected: ContextItem[] = [];
      let totalGain = 0;
      let tokensUsed = 0;

      for (const { item, gain } of scored) {
        const tokens = estimateTokens(item.content);
        if (tokensUsed + tokens > capacity) continue;

        selected.push(item);
        totalGain += gain;
        tokensUsed += tokens;
      }

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
