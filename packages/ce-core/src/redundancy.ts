import type { ContextItem } from "./types.js";

export interface EmbeddingProvider {
  embed(texts: string[]): Promise<number[][]>;
}

export interface RedundancyOptions {
  provider: EmbeddingProvider;
  similarityThreshold?: number;
  strategy?: "recent" | "summarize";
}

function cosineSimilarity(v1: number[], v2: number[]): number {
  let dotProduct = 0;
  let magnitude1 = 0;
  let magnitude2 = 0;
  for (let i = 0; i < v1.length; i++) {
    dotProduct += v1[i] * v2[i];
    magnitude1 += v1[i] * v1[i];
    magnitude2 += v2[i] * v2[i];
  }
  magnitude1 = Math.sqrt(magnitude1);
  magnitude2 = Math.sqrt(magnitude2);
  if (magnitude1 === 0 || magnitude2 === 0) return 0;
  return dotProduct / (magnitude1 * magnitude2);
}

export async function eliminateRedundancy(
  items: ContextItem[],
  options: RedundancyOptions
): Promise<ContextItem[]> {
  if (!items.length) return [];

  const threshold = options.similarityThreshold ?? 0.92;
  const strategy = options.strategy ?? "recent";
  const provider = options.provider;

  const texts = items.map((item) => item.content);
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

    const clusterItems = cluster.map((i) => items[i]);

    if (strategy === "recent" || strategy === "summarize") {
      let bestItem = clusterItems[0];
      for (const item of clusterItems) {
        const itemRecency = item.recency ?? 0;
        const bestRecency = bestItem.recency ?? 0;
        if (itemRecency > bestRecency) {
          bestItem = item;
        } else if (itemRecency === bestRecency) {
          const itemPriority = item.priority ?? 0;
          const bestPriority = bestItem.priority ?? 0;
          if (itemPriority > bestPriority) {
            bestItem = item;
          }
        }
      }
      survivingItems.push(bestItem);
    }
  }

  const finalIds = new Set(survivingItems.map((item) => item.id));
  return items.filter((item) => finalIds.has(item.id));
}
