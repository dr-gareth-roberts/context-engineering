import type { ContextItem } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import type { ResolvedConfig } from "./types.js";

/**
 * A generic chat message shape covering both OpenAI and Anthropic formats.
 * We extract what we need rather than importing SDK types directly.
 */
export interface GenericMessage {
  role: string;
  content:
    | string
    | Array<{ type: string; text?: string; [key: string]: unknown }>;
  [key: string]: unknown;
}

/** Extract plain text from a message's content field. */
export function extractText(content: GenericMessage["content"]): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter(block => block.type === "text" && typeof block.text === "string")
      .map(block => block.text as string)
      .join("\n");
  }
  return String(content ?? "");
}

/**
 * Convert an array of SDK messages into ContextItems for packing.
 *
 * Scoring heuristic:
 * - System messages get `systemPriority` (default 100)
 * - The last N messages (recentMessageCount) get priority 90 (protected)
 * - Older messages get priority decaying from 50 down to 10 based on position
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
      // Decay from 50 to 10 for older messages
      const oldCount = Math.max(1, total - protectedTail - (isSystem ? 1 : 0));
      const positionInOld = i - (messages[0]?.role === "system" ? 1 : 0);
      priority = Math.max(10, Math.round(50 - (positionInOld / oldCount) * 40));
    }

    // Recency: 0.0 (oldest) to 1.0 (newest)
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
        role: msg.role,
        isSystem,
        isProtected,
      },
    };
  });
}

/**
 * Reconstruct SDK messages from a packed result.
 *
 * Preserves the original message objects (with all SDK-specific fields)
 * by looking up each kept item's originalIndex. Inserts a summary message
 * at the gap if one was generated.
 */
export function contextItemsToMessages<T extends GenericMessage>(
  originalMessages: T[],
  keptItems: ContextItem[],
  summary?: string
): T[] {
  // Sort by original index to preserve conversation order
  const sorted = [...keptItems].sort((a, b) => {
    const aIdx = (a.metadata?.originalIndex as number) ?? 0;
    const bIdx = (b.metadata?.originalIndex as number) ?? 0;
    return aIdx - bIdx;
  });

  const result: T[] = [];
  let summaryInserted = false;

  for (const item of sorted) {
    const idx = item.metadata?.originalIndex as number;
    const originalMsg = originalMessages[idx];
    if (!originalMsg) continue;

    // Insert summary before the first non-system kept message
    // (right after the system message, replacing the gap)
    if (summary && !summaryInserted && originalMsg.role !== "system") {
      result.push({
        role: "system",
        content: `[Context summary of ${originalMessages.length - keptItems.length} earlier messages]: ${summary}`,
      } as T);
      summaryInserted = true;
    }

    result.push(originalMsg);
  }

  return result;
}
