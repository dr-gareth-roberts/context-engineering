import { getEncoding, type Tiktoken } from "js-tiktoken";
import type { TokenEstimator } from "@context-engineering/core";

let cachedEncoding: Tiktoken | null = null;

export const openaiTokenEstimator: TokenEstimator = (text: string) => {
  if (!cachedEncoding) {
    cachedEncoding = getEncoding("cl100k_base");
  }
  return cachedEncoding.encode(text).length;
};

export const anthropicTokenEstimator: TokenEstimator = (text: string) => {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  const words = trimmed.split(/\s+/).length;
  return Math.max(1, Math.ceil(words * 1.4));
};
