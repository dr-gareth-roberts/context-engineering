import type {
  ContextItem,
  Budget,
  EmbeddingProvider,
  ScoringWeights,
  QueryInput,
} from "@context-engineering/core";

/**
 * Duck-typed vector store interface — works with Pinecone, Chroma,
 * Weaviate, pgvector, or any store that can return scored results.
 */
export interface VectorStoreLike {
  query(text: string, topK: number): Promise<VectorResult[]>;
}

export interface VectorResult {
  id: string;
  content: string;
  score: number;
  metadata?: Record<string, unknown>;
}

export interface RetrieverConfig {
  store: VectorStoreLike;
  currentContext: ContextItem[];
  budget: Budget;
  embeddingProvider?: EmbeddingProvider;
  redundancyThreshold?: number;
  maxCandidates?: number;
  scoringWeights?: ScoringWeights;
}

export interface RetrieveOptions {
  topK?: number;
  minGain?: number;
  query?: QueryInput;
}

export interface RetrievedPack {
  items: ContextItem[];
  totalGain: number;
  candidatesEvaluated: number;
  candidatesFiltered: number;
  tokensUsed: number;
}

export interface InformationGainResult {
  gain: number;
  novelty: number;
  queryRelevance: number;
}

export interface InformationGainOptions {
  embeddingProvider?: EmbeddingProvider;
  queryContext?: QueryInput;
  noveltyWeight?: number;
  relevanceWeight?: number;
}

export interface HybridRetrieverConfig extends RetrieverConfig {
  bm25Weight?: number;
  vectorWeight?: number;
}

export interface ContextAwareRetriever {
  retrieve(query: string, options?: RetrieveOptions): Promise<RetrievedPack>;
}

// Re-export commonly used types from core for convenience
export type {
  ContextItem,
  Budget,
  EmbeddingProvider,
  ScoringWeights,
  QueryInput,
};
