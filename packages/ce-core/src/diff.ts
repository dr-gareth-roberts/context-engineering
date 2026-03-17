import type { ContextItem, ContextPack, PackDiff } from "./types.js";
import { ValidationError } from "./errors.js";

function normalize(input: ContextPack | ContextItem[]): ContextItem[] {
  if (Array.isArray(input)) return input;
  return input.selected ?? [];
}

/**
 * Build a Map from id to ContextItem[], grouping duplicates together.
 * This preserves all items even when duplicate IDs exist.
 */
function groupById(items: ContextItem[]): Map<string, ContextItem[]> {
  const map = new Map<string, ContextItem[]>();
  for (const item of items) {
    const group = map.get(item.id);
    if (group) {
      group.push(item);
    } else {
      map.set(item.id, [item]);
    }
  }
  return map;
}

/**
 * Compare two context packs or item arrays to find differences.
 *
 * Handles duplicate IDs correctly: if "before" has 2 items with id "x"
 * and "after" has 1 item with id "x", one will appear in "kept" or
 * "changed" and the other in "removed".
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

  const beforeGroups = groupById(beforeItems);
  const afterGroups = groupById(afterItems);

  const added: ContextItem[] = [];
  const removed: ContextItem[] = [];
  const kept: ContextItem[] = [];
  const changed: Array<{ before: ContextItem; after: ContextItem }> = [];

  // Process each ID group in "after"
  for (const [id, afterGroup] of afterGroups) {
    const beforeGroup = beforeGroups.get(id);
    if (!beforeGroup) {
      // All items with this ID are new
      added.push(...afterGroup);
      continue;
    }

    // Match items pairwise: compare by position within the group
    const maxLen = Math.max(afterGroup.length, beforeGroup.length);
    for (let i = 0; i < maxLen; i++) {
      const afterItem = afterGroup[i];
      const beforeItem = beforeGroup[i];

      if (!beforeItem) {
        // Extra item in after (more duplicates than before)
        added.push(afterItem);
      } else if (!afterItem) {
        // Extra item in before (fewer duplicates in after)
        removed.push(beforeItem);
      } else if (
        beforeItem.content !== afterItem.content ||
        beforeItem.tokens !== afterItem.tokens
      ) {
        changed.push({ before: beforeItem, after: afterItem });
      } else {
        kept.push(afterItem);
      }
    }
  }

  // Items in "before" whose ID is not in "after" at all
  for (const [id, beforeGroup] of beforeGroups) {
    if (!afterGroups.has(id)) {
      removed.push(...beforeGroup);
    }
  }

  return { added, removed, kept, changed };
}
