/**
 * Unicode-aware tokenizer. Splits on word boundaries, lowercases,
 * filters tokens with length <= 1.
 */
export function unicodeTokenize(text: string): string[] {
  if (!text) return [];
  const matches = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  return matches.filter(w => w.length > 1);
}
