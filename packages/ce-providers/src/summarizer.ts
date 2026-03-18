import type { AsyncSummarizer, ContextItem } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import type { LLMProvider } from "./types.js";

const DEFAULT_PROMPT =
  "Summarize the following conversation turns into a concise paragraph that preserves key facts, decisions, and action items. Omit pleasantries and filler.";

export function createLLMSummarizer(options: {
  provider: LLMProvider;
  model?: string;
  maxOutputTokens?: number;
  prompt?: string;
}): AsyncSummarizer {
  const {
    provider,
    model,
    maxOutputTokens = 256,
    prompt = DEFAULT_PROMPT,
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
        {
          model: model || undefined,
          maxTokens: maxOutputTokens,
        }
      );

      const content = result.text;
      if (!content) return null;

      const tokens = estimateTokens(content);
      return { ...item, content, tokens };
    } catch {
      return null;
    }
  };
}
