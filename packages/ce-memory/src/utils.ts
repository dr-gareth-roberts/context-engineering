import type { MemoryItem } from "@ce/core";
import { nanoid } from "nanoid";
import type { MemoryQuery } from "./types";

export function normalizeMemoryItem(item: Partial<MemoryItem>): MemoryItem {
  const nowIso = new Date().toISOString();
  return {
    id: item.id ?? nanoid(),
    content: item.content ?? "",
    createdAt: item.createdAt ?? nowIso,
    updatedAt: item.updatedAt ?? nowIso,
    salience: item.salience ?? 1,
    ttlSeconds: item.ttlSeconds,
    metadata: item.metadata ?? {}
  };
}

export function isExpired(item: MemoryItem, now: number): boolean {
  if (!item.ttlSeconds) return false;
  const createdAt = Date.parse(item.createdAt);
  if (Number.isNaN(createdAt)) return false;
  return createdAt + item.ttlSeconds * 1000 <= now;
}

export function decaySalience(
  item: MemoryItem,
  now: number,
  halfLifeSeconds = 60 * 60 * 24 * 30
): number {
  const createdAt = Date.parse(item.createdAt);
  if (Number.isNaN(createdAt)) return item.salience ?? 1;
  const ageSeconds = (now - createdAt) / 1000;
  const decayFactor = Math.exp((-Math.LN2 * ageSeconds) / halfLifeSeconds);
  return (item.salience ?? 1) * decayFactor;
}

export function applyQueryFilter(
  items: MemoryItem[],
  query: MemoryQuery
): MemoryItem[] {
  const now = query.now ?? Date.now();
  const includeExpired = query.includeExpired ?? false;
  const minSalience = query.minSalience ?? 0;
  const halfLifeSeconds = query.halfLifeSeconds;

  let filtered = items
    .map((item) => {
      const salience =
        halfLifeSeconds !== undefined
          ? decaySalience(item, now, halfLifeSeconds)
          : item.salience ?? 1;
      return { item, salience };
    })
    .filter(({ item, salience }) => {
    if (!includeExpired && isExpired(item, now)) return false;
    if (salience < minSalience) return false;
    if (query.text) {
      const text = query.text.toLowerCase();
      if (!item.content.toLowerCase().includes(text)) return false;
    }
    return true;
  })
    .sort((a, b) => b.salience - a.salience)
    .map(({ item }) => item);

  if (query.limit !== undefined) {
    filtered = filtered.slice(0, query.limit);
  }

  return filtered;
}
