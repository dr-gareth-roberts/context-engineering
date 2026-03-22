import type { ContextEvent, ResolvedConfig } from "./types.js";

const TAG = "[context-engineering]";

/**
 * Log a one-line summary of the context packing result to console.
 *
 * Example output:
 *   [context-engineering] 12/34 messages kept, 2,847/4,096 tokens used (69.5%), 22 trimmed
 */
export function logSummary(event: ContextEvent): void {
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
  console.log(`${TAG} ${detail}`);
}

/**
 * Build a ContextEvent from pack results and emit it to configured listeners.
 */
export function emitEvent(
  config: ResolvedConfig,
  event: ContextEvent
): void {
  if (config.log) {
    logSummary(event);
  }

  config.on.pack?.(event);

  if (event.trimmedMessages > 0) {
    config.on.trim?.(event);
  }
}
