import {
  Budget,
  ContextItem,
  ContextPack,
  PackOptions,
  TraceStep
} from "./types";
import { defaultItemScorer } from "./score";
import { estimateTokens } from "./estimate";

interface PackResult {
  pack: ContextPack;
  steps?: TraceStep[];
}

function applyCompression(
  item: ContextItem,
  remainingTokens: number,
  options: PackOptions
): { item: ContextItem; usedCompression: boolean } | null {
  if (!options.allowCompression) return null;

  const compressions = item.compressions ?? [];
  const summarizer = options.summarizer;

  const sorted = compressions
    .map((compression) => ({
      ...compression,
      tokens:
        compression.tokens ??
        estimateTokens(compression.content, { estimator: options.tokenEstimator })
    }))
    .sort((a, b) => (a.tokens ?? 0) - (b.tokens ?? 0));

  for (const compression of sorted) {
    if ((compression.tokens ?? 0) <= remainingTokens) {
      return {
        item: {
          ...item,
          content: compression.content,
          tokens: compression.tokens,
          metadata: {
            ...item.metadata,
            compressionNote: compression.note ?? "compression"
          }
        },
        usedCompression: true
      };
    }
  }

  if (summarizer) {
    const summary = summarizer(item, remainingTokens);
    if (summary) {
      const tokens =
        summary.tokens ??
        estimateTokens(summary.content, { estimator: options.tokenEstimator });
      if (tokens <= remainingTokens) {
        return {
          item: { ...summary, tokens },
          usedCompression: true
        };
      }
    }
  }

  return null;
}

export function pack(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): ContextPack {
  return internalPack(items, budget, options).pack;
}

export function internalPack(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {},
  trace = false
): PackResult {
  const scorer = options.scorer ?? defaultItemScorer;
  const tokenEstimator = options.tokenEstimator;
  const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);

  const scoredItems = items.map((item) => {
    const tokens =
      item.tokens ?? estimateTokens(item.content, { estimator: tokenEstimator });
    const score = scorer({ ...item, tokens });
    return { ...item, tokens, score };
  });

  const sorted = [...scoredItems].sort((a, b) => {
    if ((b.score ?? 0) === (a.score ?? 0)) {
      return (b.recency ?? 0) - (a.recency ?? 0);
    }
    return (b.score ?? 0) - (a.score ?? 0);
  });

  let remaining = Math.max(0, maxTokens);
  const selected: ContextItem[] = [];
  const dropped: ContextItem[] = [];
  const steps: TraceStep[] = [];

  for (const item of sorted) {
    if ((item.tokens ?? 0) <= remaining) {
      selected.push(item);
      remaining -= item.tokens ?? 0;
      if (trace) {
        steps.push({
          id: item.id,
          decision: "include",
          tokens: item.tokens,
          score: item.score,
          reason: "fits_budget"
        });
      }
      continue;
    }

    const compressed = applyCompression(item, remaining, {
      ...options,
      tokenEstimator
    });

    if (compressed) {
      selected.push(compressed.item);
      remaining -= compressed.item.tokens ?? 0;
      if (trace) {
        steps.push({
          id: item.id,
          decision: "compress",
          tokens: item.tokens,
          compressedTokens: compressed.item.tokens,
          score: item.score,
          usedCompression: true,
          reason: "compressed_to_fit"
        });
      }
    } else {
      dropped.push(item);
      if (trace) {
        steps.push({
          id: item.id,
          decision: "exclude",
          tokens: item.tokens,
          score: item.score,
          reason: "over_budget"
        });
      }
    }
  }

  const totalTokens = selected.reduce(
    (sum, item) => sum + (item.tokens ?? 0),
    0
  );

  const packResult: ContextPack = {
    budget,
    selected,
    dropped,
    totalTokens,
    stats: {
      remainingTokens: Math.max(0, maxTokens - totalTokens),
      selectedCount: selected.length,
      droppedCount: dropped.length
    }
  };

  return trace ? { pack: packResult, steps } : { pack: packResult };
}
