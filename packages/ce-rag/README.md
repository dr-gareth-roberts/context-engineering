# @context-engineering/rag

Context-aware Retrieval-Augmented Generation for the context-engineering monorepo. Unlike standard RAG that retrieves the top-K most similar chunks, this package computes **information gain** relative to what is already in the context window, ensuring retrieved chunks add genuinely new information rather than duplicating existing context.

## Quick Start

```typescript
import { createContextAwareRetriever } from "@context-engineering/rag";
import type { VectorStoreLike } from "@context-engineering/rag";

// Duck-typed — works with any vector DB that implements query()
const store: VectorStoreLike = {
  async query(text: string, topK: number) {
    // Replace with your Pinecone / Chroma / Weaviate / pgvector call
    return [
      { id: "doc-1", content: "Retrieved chunk content...", score: 0.92 },
      { id: "doc-2", content: "Another chunk...", score: 0.87 },
    ];
  },
};

const retriever = createContextAwareRetriever({
  store,
  currentContext: existingContextItems, // what's already in the prompt
  budget: { maxTokens: 4000, reserveTokens: 500 },
});

const pack = await retriever.retrieve("user question about topic X");
// pack.items — ContextItem[] ready to pass to pack()
// pack.totalGain — sum of information gain scores
// pack.candidatesFiltered — how many redundant chunks were skipped
```

## Hybrid Retrieval (Vector + BM25)

```typescript
import { createHybridRetriever } from "@context-engineering/rag";

const retriever = createHybridRetriever({
  store,
  currentContext: existingContextItems,
  budget: { maxTokens: 4000 },
  vectorWeight: 0.6, // weight for vector similarity ranking
  bm25Weight: 0.4, // weight for keyword (BM25) ranking
});

const pack = await retriever.retrieve("exact keyword search terms");
```

## API Reference

### Types

- **`VectorStoreLike`** — Duck-typed interface: `{ query(text, topK): Promise<VectorResult[]> }`
- **`VectorResult`** — `{ id, content, score, metadata? }`
- **`RetrieverConfig`** — Configuration for the context-aware retriever
- **`HybridRetrieverConfig`** — Extends RetrieverConfig with `bm25Weight` and `vectorWeight`
- **`RetrieveOptions`** — Per-query options: `topK`, `minGain`, `query`
- **`RetrievedPack`** — Result: `items`, `totalGain`, `candidatesEvaluated`, `candidatesFiltered`, `tokensUsed`
- **`InformationGainResult`** — `{ gain, novelty, queryRelevance }`
- **`ContextAwareRetriever`** — Interface: `{ retrieve(query, options?): Promise<RetrievedPack> }`

### Functions

- **`createContextAwareRetriever(config)`** — Creates a retriever that filters by information gain
- **`createHybridRetriever(config)`** — Creates a retriever using Reciprocal Rank Fusion of vector + BM25
- **`computeInformationGain(candidate, existingContext, options?)`** — Compute novelty + relevance score
- **`computeInformationGainAsync(candidate, existingContext, options?)`** — Async variant that embeds on the fly

## Design Decisions

### Why duck-typed `VectorStoreLike`?

Every vector database has a different SDK and query API. Rather than depending on any specific client library, `VectorStoreLike` requires only a single `query(text, topK)` method. This means the package works with Pinecone, Chroma, Weaviate, pgvector, Qdrant, Milvus, or any custom store — just wrap your client's search call.

### Why information gain over raw similarity?

Standard RAG retrieves the K most similar chunks to a query, regardless of what is already in the context window. This leads to redundant retrieval: if your system prompt already contains information about topic X, retrieving more chunks about X wastes tokens. Information gain scoring compares each candidate against the existing context and only keeps chunks that contribute genuinely new information, measured as `novelty * noveltyWeight + queryRelevance * relevanceWeight`.

### Integration with `pack()`

Retrieved items are standard `ContextItem[]` — pass them directly to `pack()` from `@context-engineering/core`:

```typescript
import { pack } from "@context-engineering/core";

const ragPack = await retriever.retrieve("user query");
const allItems = [...existingItems, ...ragPack.items];
const contextPack = pack(allItems, budget);
```
