import type { TokenEstimator } from "./types.js";
import { EstimationError } from "./errors.js";

/** Default token estimator using word count heuristic (words * 1.3). */
export const defaultTokenEstimator: TokenEstimator = (text: string) => {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  const words = trimmed.split(/\s+/).length;
  return Math.max(1, Math.ceil(words * 1.3));
};

/**
 * Estimate the token count for a text string.
 *
 * Uses a pluggable estimator — defaults to heuristic (words * 1.3).
 * For accurate counts, use openaiTokenEstimator from @context-engineering/providers.
 *
 * @param text - The text to estimate tokens for
 * @param options - Optional model, provider, or custom estimator
 * @returns The estimated token count
 * @throws {EstimationError} If the estimator function throws
 *
 * @example
 * ```ts
 * const count = estimateTokens("Hello world");
 * console.log(count); // 3
 * ```
 */
export function estimateTokens(
  text: string,
  options?: { model?: string; provider?: string; estimator?: TokenEstimator }
): number {
  if (text == null) return 0;
  const estimator = options?.estimator ?? defaultTokenEstimator;
  try {
    return estimator(text, {
      model: options?.model,
      provider: options?.provider,
    });
  } catch (err) {
    throw new EstimationError(
      `Token estimation failed: ${err instanceof Error ? err.message : String(err)}`
    );
  }
}
