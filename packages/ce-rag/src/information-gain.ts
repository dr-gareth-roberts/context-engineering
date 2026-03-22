import type { ContextItem } from "@context-engineering/core";
import {
  cosineSimilarity,
  computeRelevance,
  normalizeQuery,
} from "@context-engineering/core";
import { unicodeTokenize } from "@context-engineering/core";
import type { InformationGainResult, InformationGainOptions } from "./types.js";

const DEFAULT_NOVELTY_WEIGHT = 0.6;
const DEFAULT_RELEVANCE_WEIGHT = 0.4;
const NEUTRAL_RELEVANCE = 0.5;

/**
 * Compute Jaccard similarity between two token sets.
 * Matches the pattern used in ce-core/redundancy.ts.
 */
function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1;
  let intersection = 0;
  for (const word of a) {
    if (b.has(word)) intersection++;
  }
  const union = a.size + b.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

/**
 * Compute the similarity between a candidate and a single existing item.
 * Prefers embedding cosine similarity when both have embeddings,
 * falls back to Jaccard token overlap.
 */
function pairwiseSimilarity(
  candidate: ContextItem,
  existing: ContextItem,
  candidateTokens: Set<string>,
  existingTokens: Set<string>
): number {
  if (candidate.embedding && existing.embedding) {
    return Math.max(
      0,
      cosineSimilarity(candidate.embedding, existing.embedding)
    );
  }
  return jaccardSimilarity(candidateTokens, existingTokens);
}

/**
 * Compute how much new information a candidate adds relative to
 * the existing context. Higher gain means more novel + relevant content.
 */
export function computeInformationGain(
  candidate: ContextItem,
  existingContext: ContextItem[],
  options?: InformationGainOptions
): InformationGainResult {
  const noveltyWeight = options?.noveltyWeight ?? DEFAULT_NOVELTY_WEIGHT;
  const relevanceWeight = options?.relevanceWeight ?? DEFAULT_RELEVANCE_WEIGHT;

  // Novelty: 1.0 when no existing context to overlap with
  let novelty = 1.0;

  if (existingContext.length > 0) {
    const candidateTokens = new Set(unicodeTokenize(candidate.content));
    let maxSimilarity = 0;

    for (const existing of existingContext) {
      const existingTokens = new Set(unicodeTokenize(existing.content));
      const sim = pairwiseSimilarity(
        candidate,
        existing,
        candidateTokens,
        existingTokens
      );
      if (sim > maxSimilarity) {
        maxSimilarity = sim;
      }
    }

    novelty = Math.max(0, Math.min(1, 1 - maxSimilarity));
  }

  // Query relevance: use computeRelevance if query provided, else neutral
  let queryRelevance = NEUTRAL_RELEVANCE;
  if (options?.queryContext) {
    const normalized = normalizeQuery(options.queryContext);
    queryRelevance = computeRelevance(normalized, candidate);
  }

  const gain = novelty * noveltyWeight + queryRelevance * relevanceWeight;

  return { gain, novelty, queryRelevance };
}

/**
 * Async variant that uses an embedding provider to compute embeddings
 * on the fly for items that lack them.
 */
export async function computeInformationGainAsync(
  candidate: ContextItem,
  existingContext: ContextItem[],
  options?: InformationGainOptions
): Promise<InformationGainResult> {
  const provider = options?.embeddingProvider;

  if (!provider) {
    return computeInformationGain(candidate, existingContext, options);
  }

  // Collect items needing embeddings
  const textsToEmbed: string[] = [];
  const indices: Array<{ type: "candidate" | "existing"; index: number }> = [];

  if (!candidate.embedding) {
    textsToEmbed.push(candidate.content);
    indices.push({ type: "candidate", index: -1 });
  }

  for (let i = 0; i < existingContext.length; i++) {
    if (!existingContext[i].embedding) {
      textsToEmbed.push(existingContext[i].content);
      indices.push({ type: "existing", index: i });
    }
  }

  if (textsToEmbed.length === 0) {
    return computeInformationGain(candidate, existingContext, options);
  }

  const embeddings = await provider.embed(textsToEmbed);

  // Apply embeddings to copies
  let enrichedCandidate = candidate;
  const enrichedContext = [...existingContext];

  for (let i = 0; i < indices.length; i++) {
    const entry = indices[i];
    if (entry.type === "candidate") {
      enrichedCandidate = { ...candidate, embedding: embeddings[i] };
    } else {
      enrichedContext[entry.index] = {
        ...existingContext[entry.index],
        embedding: embeddings[i],
      };
    }
  }

  return computeInformationGain(enrichedCandidate, enrichedContext, options);
}
