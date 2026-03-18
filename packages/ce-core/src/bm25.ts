/**
 * Unicode-aware tokenizer. Splits on word boundaries, lowercases,
 * filters tokens with length <= 1.
 */
export function unicodeTokenize(text: string): string[] {
  if (!text) return [];
  const matches = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  return matches.filter(w => w.length > 1);
}

export interface BM25Index {
  add(id: string, text: string): void;
  score(query: string, id: string): number;
  scoreAll(query: string): Map<string, number>;
  readonly documentCount: number;
}

export function createBM25Index(options?: {
  k1?: number;
  b?: number;
  tokenizer?: (text: string) => string[];
}): BM25Index {
  const k1 = options?.k1 ?? 1.2;
  const b = options?.b ?? 0.75;
  const tokenize = options?.tokenizer ?? unicodeTokenize;

  const docs = new Map<string, Map<string, number>>();
  const docLengths = new Map<string, number>();
  const df = new Map<string, number>();
  let totalLength = 0;

  function add(id: string, text: string): void {
    const tokens = tokenize(text);
    const freq = new Map<string, number>();
    for (const t of tokens) {
      freq.set(t, (freq.get(t) ?? 0) + 1);
    }
    docs.set(id, freq);
    docLengths.set(id, tokens.length);
    totalLength += tokens.length;
    for (const term of freq.keys()) {
      df.set(term, (df.get(term) ?? 0) + 1);
    }
  }

  function score(query: string, id: string): number {
    const docFreq = docs.get(id);
    if (!docFreq) return 0;
    const queryTokens = tokenize(query);
    if (queryTokens.length === 0) return 0;

    const N = docs.size;
    const dl = docLengths.get(id) ?? 0;
    const avgdl = N > 0 ? totalLength / N : 1;
    let total = 0;

    for (const term of queryTokens) {
      const termDf = df.get(term) ?? 0;
      const tf = docFreq.get(term) ?? 0;
      if (tf === 0) continue;
      const idf = Math.log((N - termDf + 0.5) / (termDf + 0.5) + 1);
      const tfNorm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + (b * dl) / avgdl));
      total += idf * tfNorm;
    }
    return total;
  }

  function scoreAll(query: string): Map<string, number> {
    const result = new Map<string, number>();
    for (const id of docs.keys()) {
      result.set(id, score(query, id));
    }
    return result;
  }

  return {
    add,
    score,
    scoreAll,
    get documentCount() {
      return docs.size;
    },
  };
}
