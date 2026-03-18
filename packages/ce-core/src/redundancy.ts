import { cosineSimilarity } from "./relevance.js";
import { unicodeTokenize } from "./bm25.js";
import type { ContextItem, EmbeddingProvider } from "./types.js";

export interface RedundancyOptions {
  /** Similarity threshold. Default: 0.85 (embedding), 0.8 (Jaccard) */
  threshold?: number;
  /** Strategy for picking surviving item in a cluster */
  strategy?: "recent" | "highest-priority";
  /** Embedding provider for cosine similarity. If omitted, Jaccard fallback is used. */
  embeddingProvider?: EmbeddingProvider;
  /** Custom tokenizer for Jaccard mode */
  tokenizer?: (text: string) => string[];
}

function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1;
  let intersection = 0;
  for (const word of a) {
    if (b.has(word)) intersection++;
  }
  const union = a.size + b.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

function resolveSurvivor(
  clusterItems: ContextItem[],
  strategy: "recent" | "highest-priority"
): ContextItem {
  if (strategy === "highest-priority") {
    return clusterItems.reduce((best, item) => {
      const itemPriority = item.priority ?? 0;
      const bestPriority = best.priority ?? 0;
      if (itemPriority > bestPriority) return item;
      if (
        itemPriority === bestPriority &&
        (item.recency ?? 0) > (best.recency ?? 0)
      )
        return item;
      return best;
    });
  }
  // "recent" strategy
  return clusterItems.reduce((best, item) => {
    const itemRecency = item.recency ?? 0;
    const bestRecency = best.recency ?? 0;
    if (itemRecency > bestRecency) return item;
    if (
      itemRecency === bestRecency &&
      (item.priority ?? 0) > (best.priority ?? 0)
    )
      return item;
    return best;
  });
}

export function eliminateRedundancySync(
  items: ContextItem[],
  options: Omit<RedundancyOptions, "embeddingProvider"> = {}
): ContextItem[] {
  if (items.length <= 1) return items;

  const threshold = options.threshold ?? 0.8;
  const strategy = options.strategy ?? "recent";
  const tokenize = options.tokenizer ?? unicodeTokenize;

  // Tokenize all items
  const wordSets = items.map(item => new Set(tokenize(item.content)));

  // Leader clustering
  const clusters: number[][] = [];
  for (let i = 0; i < items.length; i++) {
    let added = false;
    for (const cluster of clusters) {
      const similarity = jaccardSimilarity(wordSets[i], wordSets[cluster[0]]);
      if (similarity >= threshold) {
        cluster.push(i);
        added = true;
        break;
      }
    }
    if (!added) {
      clusters.push([i]);
    }
  }

  // Resolve clusters
  const survivingItems: ContextItem[] = [];
  for (const cluster of clusters) {
    if (cluster.length === 1) {
      survivingItems.push(items[cluster[0]]);
    } else {
      survivingItems.push(
        resolveSurvivor(
          cluster.map(i => items[i]),
          strategy
        )
      );
    }
  }

  // Maintain original order
  const survivors = new Set(survivingItems);
  return items.filter(item => survivors.has(item));
}

export async function eliminateRedundancy(
  items: ContextItem[],
  options: RedundancyOptions
): Promise<ContextItem[]> {
  if (!items.length) return [];

  // If no embedding provider, fall back to sync Jaccard
  if (!options.embeddingProvider) {
    return eliminateRedundancySync(items, options);
  }

  const threshold = options.threshold ?? 0.85;
  const strategy = options.strategy ?? "recent";
  const provider = options.embeddingProvider;

  const texts = items.map(item => item.content);
  const embeddings = await provider.embed(texts);

  const clusters: number[][] = [];

  for (let i = 0; i < embeddings.length; i++) {
    const emb = embeddings[i];
    let added = false;
    for (const cluster of clusters) {
      const firstIdx = cluster[0];
      const similarity = cosineSimilarity(emb, embeddings[firstIdx]);
      if (similarity >= threshold) {
        cluster.push(i);
        added = true;
        break;
      }
    }
    if (!added) {
      clusters.push([i]);
    }
  }

  const survivingItems: ContextItem[] = [];

  for (const cluster of clusters) {
    if (cluster.length === 1) {
      survivingItems.push(items[cluster[0]]);
      continue;
    }

    const clusterItems = cluster.map(i => items[i]);
    survivingItems.push(resolveSurvivor(clusterItems, strategy));
  }

  const survivors = new Set(survivingItems);
  return items.filter(item => survivors.has(item));
}
