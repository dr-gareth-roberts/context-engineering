import { pack } from "@context-engineering/core";
import type { ContextPack } from "@context-engineering/core";
import { MODEL_METADATA } from "@context-engineering/providers";
import type { ResolvedConfig, ContextEvent } from "./types.js";
import {
  messagesToContextItems,
  contextItemsToMessages,
  type GenericMessage,
} from "./message-converter.js";
import { applyStrategy } from "./strategy.js";
import { emitEvent } from "./logger.js";

type Provider = "openai" | "anthropic";

/**
 * Look up the context window size for a model string.
 * Falls back to a conservative default if the model isn't in MODEL_METADATA.
 */
function getModelBudget(
  model: string,
  provider: Provider
): number {
  const providerMeta = MODEL_METADATA[provider] as Record<
    string,
    { maxTokens: number }
  >;
  const meta = providerMeta?.[model];
  // Default to 128k if model isn't recognized
  return meta?.maxTokens ?? 128000;
}

/**
 * Core interception logic shared by both OpenAI and Anthropic wrappers.
 *
 * Takes the original messages array, packs them within the token budget,
 * applies the configured strategy for dropped messages, and returns
 * the new messages array ready to send to the API.
 */
export async function interceptMessages<T extends GenericMessage>(
  messages: T[],
  model: string,
  provider: Provider,
  config: ResolvedConfig
): Promise<T[]> {
  const start = performance.now();

  // Determine token budget
  const modelBudget = config.budget ?? getModelBudget(model, provider);
  const budget = {
    maxTokens: modelBudget - config.reserveTokens,
    reserveTokens: 0,
  };

  // If the budget is absurdly large relative to the messages, skip packing
  const items = messagesToContextItems(messages, config);
  const totalTokens = items.reduce((sum, item) => sum + (item.tokens ?? 0), 0);

  if (totalTokens <= budget.maxTokens) {
    // Everything fits — no packing needed
    const elapsed = performance.now() - start;
    const event: ContextEvent = {
      timestamp: Date.now(),
      model,
      totalMessages: messages.length,
      keptMessages: messages.length,
      trimmedMessages: 0,
      summarized: false,
      tokensUsed: totalTokens,
      tokenBudget: modelBudget,
      utilization: modelBudget > 0 ? (totalTokens / modelBudget) * 100 : 0,
      packTimeMs: Math.round(elapsed),
    };
    emitEvent(config, event);
    return messages;
  }

  // Pack: score and select items within budget
  const packResult: ContextPack = pack(items, budget);

  // Apply strategy (trim, summarize, or custom)
  const summary = await applyStrategy(config.strategy, messages, packResult);

  // Reconstruct messages from pack result
  const result = contextItemsToMessages(messages, packResult.selected, summary);

  const elapsed = performance.now() - start;
  const trimmedCount = messages.length - packResult.selected.length;
  const event: ContextEvent = {
    timestamp: Date.now(),
    model,
    totalMessages: messages.length,
    keptMessages: packResult.selected.length,
    trimmedMessages: trimmedCount,
    summarized: summary !== undefined,
    tokensUsed: packResult.totalTokens,
    tokenBudget: modelBudget,
    utilization: modelBudget > 0 ? (packResult.totalTokens / modelBudget) * 100 : 0,
    packTimeMs: Math.round(elapsed),
    pack: config.includePack ? packResult : undefined,
  };

  emitEvent(config, event);

  return result;
}
