import type { ContextPack } from "@context-engineering/core";
import type { ContextStrategy, DroppedMessage } from "./types.js";
import { extractText, type GenericMessage } from "./message-converter.js";
import { estimateTokens } from "@context-engineering/core";

/**
 * Apply the configured context strategy to handle dropped messages.
 *
 * @returns A summary string if the strategy produced one, undefined otherwise.
 */
export async function applyStrategy(
  strategy: ContextStrategy,
  originalMessages: GenericMessage[],
  pack: ContextPack
): Promise<string | undefined> {
  if (strategy === "trim") {
    // Trim strategy: just drop messages, no summary needed
    return undefined;
  }

  // Build the list of dropped messages for the summarizer
  const keptIndices = new Set(
    pack.selected.map(item => item.metadata?.originalIndex as number)
  );

  const dropped: DroppedMessage[] = originalMessages
    .map((msg, i) => ({
      role: msg.role,
      content: extractText(msg.content),
      tokens: estimateTokens(extractText(msg.content)),
      index: i,
    }))
    .filter((_, i) => !keptIndices.has(i));

  if (dropped.length === 0) return undefined;

  if (strategy === "summarize") {
    // Built-in summarize: create a concise bullet-point summary
    return defaultSummarize(dropped);
  }

  // Custom function
  return strategy(dropped);
}

/**
 * Default summarization: produces a bullet-point digest of dropped messages.
 * This is a local heuristic — no LLM call. For LLM-powered summaries,
 * pass a custom SummarizeFunction that uses createLLMSummarizer from ce-providers.
 */
function defaultSummarize(dropped: DroppedMessage[]): string {
  const lines = dropped.map(msg => {
    const preview =
      msg.content.length > 120
        ? msg.content.slice(0, 120) + "..."
        : msg.content;
    return `- [${msg.role}]: ${preview}`;
  });

  return `Earlier conversation (${dropped.length} messages, summarized):\n${lines.join("\n")}`;
}
