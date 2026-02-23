import type { ContextItem, ItemScorer } from "./types";

export const defaultItemScorer: ItemScorer = (item: ContextItem) => {
  if (typeof item.score === "number") return item.score;

  const priority = item.priority ?? 0;
  const recency = item.recency ?? 0;
  const metadataScore =
    typeof item.metadata?.salience === "number"
      ? (item.metadata?.salience as number)
      : 0;

  return priority * 1.0 + recency * 0.7 + metadataScore * 0.5;
};
