import type { ContextItem, ContextPack, PackDiff } from "./types.js";
import { ValidationError } from "./errors.js";

function normalize(input: ContextPack | ContextItem[]): ContextItem[] {
  if (Array.isArray(input)) return input;
  return input.selected ?? [];
}

/**
 * Compare two context packs or item arrays to find differences.
 *
 * @param before - The original context pack or items
 * @param after - The updated context pack or items
 * @returns A PackDiff with added, removed, kept, and changed items
 * @throws {ValidationError} If before or after is null/undefined
 *
 * @example
 * ```ts
 * const changes = diff(oldPack, newPack);
 * console.log(`${changes.added.length} new items`);
 * ```
 */
export function diff(
  before: ContextPack | ContextItem[],
  after: ContextPack | ContextItem[]
): PackDiff {
  if (!before) {
    throw new ValidationError("diff() 'before' argument is required");
  }
  if (!after) {
    throw new ValidationError("diff() 'after' argument is required");
  }

  const beforeItems = normalize(before);
  const afterItems = normalize(after);

  const beforeMap = new Map(beforeItems.map(item => [item.id, item]));
  const afterMap = new Map(afterItems.map(item => [item.id, item]));

  const added: ContextItem[] = [];
  const removed: ContextItem[] = [];
  const kept: ContextItem[] = [];
  const changed: Array<{ before: ContextItem; after: ContextItem }> = [];

  afterMap.forEach((item, id) => {
    if (!beforeMap.has(id)) {
      added.push(item);
      return;
    }

    const prev = beforeMap.get(id) as ContextItem;
    if (prev.content !== item.content || prev.tokens !== item.tokens) {
      changed.push({ before: prev, after: item });
    } else {
      kept.push(item);
    }
  });

  beforeMap.forEach((item, id) => {
    if (!afterMap.has(id)) {
      removed.push(item);
    }
  });

  return { added, removed, kept, changed };
}
