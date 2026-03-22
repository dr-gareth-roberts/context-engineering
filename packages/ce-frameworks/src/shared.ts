import { pack, estimateTokens } from "@context-engineering/core";
import type { ContextItem, ContextPack } from "@context-engineering/core";
import type {
  GenericMessage,
  ContextEvent,
  DroppedMessage,
  ResolvedConfig,
  ContextStrategy,
} from "./types.js";

const TAG = "[context-engineering]";

/**
 * Extract plain text from message content.
 * Handles string content and structured content arrays.
 */
export function extractText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter(
        (block): block is { type: string; text: string } =>
          typeof block === "object" &&
          block !== null &&
          block.type === "text" &&
          typeof block.text === "string"
      )
      .map(block => block.text)
      .join("\n");
  }
  if (content != null && typeof content === "object") {
    return JSON.stringify(content);
  }
  return String(content ?? "");
}

/**
 * Convert generic messages to ContextItems for scoring and packing.
 *
 * Scoring heuristic:
 * - System messages get `systemPriority` (default 100)
 * - The last N messages (recentMessageCount) get priority 90 (protected)
 * - Older messages decay from 50 down to 10 based on position
 */
export function messagesToContextItems(
  messages: GenericMessage[],
  config: ResolvedConfig
): ContextItem[] {
  const total = messages.length;
  const protectedTail = config.recentMessageCount;

  return messages.map((msg, i) => {
    const text = extractText(msg.content);
    const tokens = estimateTokens(text);
    const isSystem = msg.role === "system";
    const isProtected = i >= total - protectedTail;

    let priority: number;
    if (isSystem) {
      priority = config.systemPriority;
    } else if (isProtected) {
      priority = 90;
    } else {
      const oldCount = Math.max(1, total - protectedTail - (isSystem ? 1 : 0));
      const positionInOld = i - (messages[0]?.role === "system" ? 1 : 0);
      priority = Math.max(10, Math.round(50 - (positionInOld / oldCount) * 40));
    }

    const recency = total > 1 ? i / (total - 1) : 1;

    return {
      id: `msg-${i}`,
      content: text,
      kind: msg.role,
      priority,
      recency,
      tokens,
      metadata: {
        originalIndex: i,
        originalMessage: msg,
        role: msg.role,
        isSystem,
        isProtected,
      },
    };
  });
}

/**
 * Reconstruct GenericMessage[] from packed ContextItems.
 * Preserves original message objects via metadata and restores conversation order.
 * Optionally injects a summary message for dropped content.
 */
export function contextItemsToMessages(
  originalMessages: GenericMessage[],
  keptItems: ContextItem[],
  summary?: string
): GenericMessage[] {
  const sorted = [...keptItems].sort((a, b) => {
    const aIdx = (a.metadata?.originalIndex as number) ?? 0;
    const bIdx = (b.metadata?.originalIndex as number) ?? 0;
    return aIdx - bIdx;
  });

  const result: GenericMessage[] = [];
  let summaryInserted = false;

  for (const item of sorted) {
    const idx = item.metadata?.originalIndex as number;
    const original =
      (item.metadata?.originalMessage as GenericMessage) ??
      originalMessages[idx];
    if (!original) continue;

    // Insert summary before the first non-system kept message
    if (summary && !summaryInserted && original.role !== "system") {
      result.push({
        role: "system",
        content: `[Context summary of ${originalMessages.length - keptItems.length} earlier messages]: ${summary}`,
      });
      summaryInserted = true;
    }

    result.push(original);
  }

  return result;
}

/**
 * Apply the configured strategy for dropped messages.
 * Returns a summary string if one was generated.
 */
async function applyStrategy(
  strategy: ContextStrategy,
  originalMessages: GenericMessage[],
  packResult: ContextPack
): Promise<string | undefined> {
  if (strategy === "trim") return undefined;

  const keptIndices = new Set(
    packResult.selected.map(item => item.metadata?.originalIndex as number)
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
    return defaultSummarize(dropped);
  }

  // Custom summarize function
  return strategy(dropped);
}

/** Default local summarization: bullet-point digest of dropped messages. */
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

/** Log a one-line summary to console. */
function logSummary(event: ContextEvent): void {
  const kept = event.keptMessages;
  const total = event.totalMessages;
  const tokensUsed = event.tokensUsed.toLocaleString();
  const budget = event.tokenBudget.toLocaleString();
  const util = event.utilization.toFixed(1);
  const trimmed = event.trimmedMessages;

  let detail = `${kept}/${total} messages kept, ${tokensUsed}/${budget} tokens (${util}%)`;
  if (trimmed > 0) {
    detail += `, ${trimmed} trimmed`;
  }
  if (event.summarized) {
    detail += " + summary injected";
  }

  // eslint-disable-next-line no-console
  console.log(`${TAG} [${event.framework}] ${detail}`);
}

/** Emit the event to configured listeners and optionally log to console. */
function emitEvent(config: ResolvedConfig, event: ContextEvent): void {
  if (config.log) {
    logSummary(event);
  }
  config.on.pack?.(event);
  if (event.trimmedMessages > 0) {
    config.on.trim?.(event);
  }
}

/**
 * Core packing logic shared by all framework adapters.
 *
 * Converts generic messages to ContextItems, packs them within budget,
 * applies the configured strategy for dropped messages, and converts back.
 */
export async function packMessages(
  messages: GenericMessage[],
  model: string,
  framework: string,
  config: ResolvedConfig
): Promise<{
  packed: GenericMessage[];
  event: ContextEvent;
}> {
  const start = performance.now();
  const effectiveBudget = config.budget - config.reserveTokens;

  const items = messagesToContextItems(messages, config);
  const totalTokens = items.reduce((sum, item) => sum + (item.tokens ?? 0), 0);

  // If everything fits, pass through unchanged
  if (totalTokens <= effectiveBudget) {
    const elapsed = performance.now() - start;
    const event: ContextEvent = {
      timestamp: Date.now(),
      framework,
      model,
      totalMessages: messages.length,
      keptMessages: messages.length,
      trimmedMessages: 0,
      summarized: false,
      tokensUsed: totalTokens,
      tokenBudget: config.budget,
      utilization: config.budget > 0 ? (totalTokens / config.budget) * 100 : 0,
      packTimeMs: Math.round(elapsed),
    };
    emitEvent(config, event);
    return { packed: messages, event };
  }

  // Pack: score and select items within budget
  const packResult: ContextPack = pack(
    items,
    {
      maxTokens: effectiveBudget,
      reserveTokens: 0,
    },
    config.weights ? { weights: config.weights } : undefined
  );

  // Record for replay if a recorder is attached
  if (config.recorder) {
    config.recorder.record({
      model,
      items,
      budget: { maxTokens: effectiveBudget, reserveTokens: 0 },
      result: packResult,
      metadata: { framework },
    });
  }

  // Apply strategy (trim, summarize, or custom)
  const summary = await applyStrategy(config.strategy, messages, packResult);

  // Reconstruct messages from pack result
  const packed = contextItemsToMessages(messages, packResult.selected, summary);

  const elapsed = performance.now() - start;
  const trimmedCount = messages.length - packResult.selected.length;
  const event: ContextEvent = {
    timestamp: Date.now(),
    framework,
    model,
    totalMessages: messages.length,
    keptMessages: packResult.selected.length,
    trimmedMessages: trimmedCount,
    summarized: summary !== undefined,
    tokensUsed: packResult.totalTokens,
    tokenBudget: config.budget,
    utilization:
      config.budget > 0 ? (packResult.totalTokens / config.budget) * 100 : 0,
    packTimeMs: Math.round(elapsed),
  };

  emitEvent(config, event);

  return { packed, event };
}
