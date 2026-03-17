import { getEncoding, type Tiktoken } from "js-tiktoken";
import type { TokenEstimator } from "@context-engineering/core";

/**
 * Models that use the older cl100k_base encoding.
 * Everything else (GPT-4o, GPT-4.1, o-series) uses o200k_base.
 */
const CL100K_MODELS = new Set([
  "gpt-4",
  "gpt-4-turbo",
  "gpt-4-turbo-preview",
  "gpt-4-0125-preview",
  "gpt-4-1106-preview",
  "gpt-3.5-turbo",
  "gpt-3.5-turbo-0125",
  "gpt-3.5-turbo-1106",
  "gpt-3.5-turbo-16k",
  "text-embedding-ada-002",
]);

let cachedO200k: Tiktoken | null = null;
let cachedCl100k: Tiktoken | null = null;

function getEncodingForModel(model?: string): Tiktoken {
  if (model && CL100K_MODELS.has(model)) {
    if (!cachedCl100k) {
      cachedCl100k = getEncoding("cl100k_base");
    }
    return cachedCl100k;
  }
  // Default: o200k_base (GPT-4o, GPT-4.1, o1, o3, o4-mini, etc.)
  if (!cachedO200k) {
    cachedO200k = getEncoding("o200k_base");
  }
  return cachedO200k;
}

/**
 * Token estimator using tiktoken for OpenAI models.
 *
 * Uses o200k_base encoding by default (GPT-4o, GPT-4.1, o-series).
 * Falls back to cl100k_base for older models (GPT-4, GPT-3.5) when
 * `options.model` is provided.
 */
export const openaiTokenEstimator: TokenEstimator = (
  text: string,
  options?: { model?: string; provider?: string }
) => {
  if (!text) return 0;
  const encoding = getEncodingForModel(options?.model);
  return encoding.encode(text).length;
};

/**
 * Token estimator using word-count heuristic for Anthropic models.
 *
 * Approximation: words * 1.4, minimum 1 token for non-empty input.
 */
export const anthropicTokenEstimator: TokenEstimator = (
  text: string,
  _options?: { model?: string; provider?: string }
) => {
  if (!text) return 0;
  const trimmed = text.trim();
  if (!trimmed) return 0;
  const words = trimmed.split(/\s+/).length;
  return Math.max(1, Math.ceil(words * 1.4));
};
