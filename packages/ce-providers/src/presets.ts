import {
  openaiTokenEstimator,
  anthropicTokenEstimator,
} from "./token-estimators.js";
import type { TokenEstimator } from "@ce/core";

interface ProviderPreset {
  estimator: TokenEstimator;
}

/**
 * Pre-configured provider settings for common LLM providers.
 *
 * @example
 * ```ts
 * import { presets } from "@ce/providers";
 * import { pack } from "@ce/core";
 *
 * const result = pack(items, budget, {
 *   tokenEstimator: presets.openai.estimator,
 * });
 * ```
 */
export const presets = {
  openai: {
    estimator: openaiTokenEstimator,
  } satisfies ProviderPreset,
  anthropic: {
    estimator: anthropicTokenEstimator,
  } satisfies ProviderPreset,
};
