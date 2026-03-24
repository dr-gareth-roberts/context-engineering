/**
 * Convergence scoring for Delphi strategy.
 *
 * Measures how much agreement exists between expert responses
 * using token-level Jaccard similarity across all pairs.
 */

import type { MemberResponse } from "./types.js";

/**
 * Tokenize text into lowercase word tokens.
 */
function tokenize(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .split(/[\s\p{P}]+/u)
      .filter(w => w.length > 2)
  );
}

/**
 * Compute Jaccard similarity between two token sets.
 */
function jaccard(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1;
  let intersection = 0;
  for (const token of a) {
    if (b.has(token)) intersection++;
  }
  const union = a.size + b.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

/**
 * Compute the average pairwise similarity across all member responses.
 * Returns a score between 0 (total disagreement) and 1 (identical responses).
 */
export function computeConvergence(responses: MemberResponse[]): number {
  if (responses.length < 2) return 1;

  const tokenSets = responses.map(r => tokenize(r.response));
  let totalSimilarity = 0;
  let pairCount = 0;

  for (let i = 0; i < tokenSets.length; i++) {
    for (let j = i + 1; j < tokenSets.length; j++) {
      totalSimilarity += jaccard(tokenSets[i], tokenSets[j]);
      pairCount++;
    }
  }

  return pairCount > 0 ? totalSimilarity / pairCount : 1;
}
