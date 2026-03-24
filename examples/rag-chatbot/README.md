# RAG Chatbot Example

Demonstrates how context-engineering manages the full retrieval-augmented generation loop: retrieve documents, filter by information gain, pack into a budget-aware context window, and optimise for prefix caching.

No API keys or external services needed. Everything runs locally with mock data.

## Run

```bash
npx tsx examples/rag-chatbot/index.ts
```

## What it does

1. **Creates an in-memory vector store** with 10 sample API documentation pages (auth, rate limits, endpoints, errors, etc.)
2. **Retrieves relevant documents** for the query "How do I authenticate and handle rate limits?" using keyword-based similarity scoring
3. **Filters by information gain** via `createContextAwareRetriever` -- candidates that overlap heavily with existing context (system prompt, conversation history) are dropped
4. **Packs into a pipeline** with `pipeline()`, applying:
   - Budget allocation (system 15%, retrieval 60%, conversation 25%)
   - Cache topology optimisation for Anthropic prefix caching
   - Quality gate (minimum 0.3 overall score)
5. **Runs two scenarios** -- a comfortable 2000-token budget and a tight 600-token budget -- to show graceful degradation
6. **Prints a comparison** of quality metrics, token usage, and cache efficiency between the two budgets

## Key concepts

| Concept             | What it does                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Information gain    | Scores candidates for novelty relative to existing context -- avoids paying tokens for redundant content            |
| Pipeline allocation | Distributes budget across context kinds (system, retrieval, conversation) with min/max/target constraints           |
| Cache topology      | Orders items so the stable prefix stays consistent across requests, enabling ~90% cost reduction via prefix caching |
| Quality gate        | Analyzes density, diversity, freshness, and redundancy to ensure the packed context meets a quality threshold       |

## Expected output

The script prints colour-formatted tables showing:

- Retrieved documents with vector scores and information gain bars
- Pipeline selection/drop decisions with token counts
- Quality metric breakdowns (density, diversity, freshness, redundancy)
- Cache efficiency and allocation efficiency percentages
- Side-by-side comparison of both budget scenarios
