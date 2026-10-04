import type { AsyncSummarizer, ContextItem } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import type { LLMProvider } from "./types.js";

const DEFAULT_PROMPT =
  "Summarize the following conversation turns into a concise paragraph that preserves key facts, decisions, and action items. Omit pleasantries and filler.";

/**
 * Create an async summarizer backed by an LLM provider.
 *
 * On provider errors the summarizer returns `null` (callers fall back to
 * truncation) and reports the error via `onError`, or `console.warn` when no
 * callback is supplied. When `model` is omitted the provider default is used.
 */
export function createLLMSummarizer(options: {
  provider: LLMProvider;
  model?: string;
  maxOutputTokens?: number;
  prompt?: string;
  onError?: (error: unknown) => void;
}): AsyncSummarizer {
  const {
    provider,
    model,
    maxOutputTokens = 256,
    prompt = DEFAULT_PROMPT,
    onError,
  } = options;

  return async (
    item: ContextItem,
    _targetTokens: number
  ): Promise<ContextItem | null> => {
    try {
      const result = await provider.generate(
        [
          { role: "system", content: prompt },
          { role: "user", content: item.content },
        ],
        // Omit model when unset so the provider's default applies.
        model
          ? { model, maxTokens: maxOutputTokens }
          : { maxTokens: maxOutputTokens }
      );

      const content = result.text;
      if (!content) return null;

      const tokens = estimateTokens(content);
      return { ...item, content, tokens };
    } catch (error) {
      // Fall back to truncation (null), but never fail silently.
      if (onError) {
        onError(error);
      } else {
        console.warn("[context-engineering] LLM summarizer failed", error);
      }
      return null;
    }
  };
}
