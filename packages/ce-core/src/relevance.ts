import type {
  ContextItem,
  EmbeddingProvider,
  QueryContext,
  QueryInput,
} from "./types.js";

const STOPWORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "but",
  "by",
  "for",
  "from",
  "had",
  "has",
  "have",
  "he",
  "her",
  "his",
  "how",
  "i",
  "if",
  "in",
  "into",
  "is",
  "it",
  "its",
  "just",
  "me",
  "my",
  "no",
  "nor",
  "not",
  "of",
  "on",
  "or",
  "our",
  "out",
  "own",
  "she",
  "so",
  "some",
  "than",
  "that",
  "the",
  "their",
  "them",
  "then",
  "there",
  "these",
  "they",
  "this",
  "to",
  "too",
  "up",
  "us",
  "was",
  "we",
  "were",
  "what",
  "when",
  "which",
  "who",
  "will",
  "with",
  "would",
  "you",
  "your",
]);

/**
 * Normalize a query input into a QueryContext.
 */
export function normalizeQuery(input: QueryInput): QueryContext {
  if (typeof input === "string") {
    return { text: input, keywords: [...extractKeywords(input)] };
  }
  return {
    ...input,
    keywords: input.keywords ?? [...extractKeywords(input.text)],
  };
}

/**
 * Extract keywords from text: tokenize, lowercase, filter stopwords.
 */
export function extractKeywords(text: string): Set<string> {
  const words = text.toLowerCase().match(/[a-z0-9]+/g) ?? [];
  return new Set(words.filter(w => w.length > 1 && !STOPWORDS.has(w)));
}

/**
 * Compute keyword relevance using asymmetric Jaccard.
 * Returns the fraction of query keywords found in the item content.
 */
export function keywordRelevance(
  query: QueryContext,
  item: ContextItem
): number {
  const queryKeywords = query.keywords ?? [...extractKeywords(query.text)];
  if (queryKeywords.length === 0) return 0;

  const itemKeywords = extractKeywords(item.content);
  let found = 0;
  for (const kw of queryKeywords) {
    if (itemKeywords.has(kw)) found++;
  }
  return found / queryKeywords.length;
}

/**
 * Compute cosine similarity between two vectors.
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) return 0;
  let dotProduct = 0;
  let magnitude1 = 0;
  let magnitude2 = 0;
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    magnitude1 += a[i] * a[i];
    magnitude2 += b[i] * b[i];
  }
  magnitude1 = Math.sqrt(magnitude1);
  magnitude2 = Math.sqrt(magnitude2);
  if (magnitude1 === 0 || magnitude2 === 0) return 0;
  return dotProduct / (magnitude1 * magnitude2);
}

/**
 * Compute embedding-based relevance via cosine similarity.
 * Returns 0 if either embedding is missing.
 */
export function embeddingRelevance(
  queryEmbedding: number[] | undefined,
  itemEmbedding: number[] | undefined
): number {
  if (!queryEmbedding || !itemEmbedding) return 0;
  const sim = cosineSimilarity(queryEmbedding, itemEmbedding);
  // Clamp to [0, 1] — negative cosine similarity means anti-correlated
  return Math.max(0, sim);
}

/**
 * Compute relevance of an item to a query.
 * Uses embedding similarity if available, falls back to keyword matching.
 */
export function computeRelevance(
  query: QueryContext,
  item: ContextItem
): number {
  if (query.embedding && item.embedding) {
    return embeddingRelevance(query.embedding, item.embedding);
  }
  return keywordRelevance(query, item);
}

/**
 * Batch-embed items that lack embeddings, and enrich the query if needed.
 */
export async function enrichWithEmbeddings(
  items: ContextItem[],
  query: QueryContext,
  provider: EmbeddingProvider
): Promise<{ items: ContextItem[]; query: QueryContext }> {
  const needsEmbedding: number[] = [];
  const texts: string[] = [];

  // Collect items that need embeddings
  for (let i = 0; i < items.length; i++) {
    if (!items[i].embedding) {
      needsEmbedding.push(i);
      texts.push(items[i].content);
    }
  }

  // Include query text if it lacks an embedding
  const needsQueryEmbedding = !query.embedding;
  if (needsQueryEmbedding) {
    texts.push(query.text);
  }

  if (texts.length === 0) {
    return { items, query };
  }

  const embeddings = await provider.embed(texts);

  // Apply embeddings to items
  const enrichedItems = [...items];
  for (let i = 0; i < needsEmbedding.length; i++) {
    const idx = needsEmbedding[i];
    enrichedItems[idx] = { ...enrichedItems[idx], embedding: embeddings[i] };
  }

  // Apply embedding to query
  let enrichedQuery = query;
  if (needsQueryEmbedding) {
    enrichedQuery = {
      ...query,
      embedding: embeddings[embeddings.length - 1],
    };
  }

  return { items: enrichedItems, query: enrichedQuery };
}
