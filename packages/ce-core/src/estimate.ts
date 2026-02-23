import type { TokenEstimator } from "./types";
import { EstimationError } from "./errors";

export const defaultTokenEstimator: TokenEstimator = (text: string) => {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  const words = trimmed.split(/\s+/).length;
  return Math.max(1, Math.ceil(words * 1.3));
};

export function estimateTokens(
  text: string,
  options?: { model?: string; provider?: string; estimator?: TokenEstimator }
): number {
  if (text == null) return 0;
  const estimator = options?.estimator ?? defaultTokenEstimator;
  try {
    return estimator(text, { model: options?.model, provider: options?.provider });
  } catch (err) {
    throw new EstimationError(
      `Token estimation failed: ${err instanceof Error ? err.message : String(err)}`
    );
  }
}
