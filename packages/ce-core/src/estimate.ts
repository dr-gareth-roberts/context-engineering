import type { TokenEstimator } from "./types";

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
  const estimator = options?.estimator ?? defaultTokenEstimator;
  return estimator(text, { model: options?.model, provider: options?.provider });
}
