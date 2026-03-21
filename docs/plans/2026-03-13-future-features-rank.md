# Future Features Priority Ranking

> Updated March 2026. Items 3 and 4 have been implemented.

1. Ecosystem Connectors (LangChain & LlamaIndex) - Highest ROI, enables immediate adoption by Python developers using existing frameworks. Low complexity.
2. Context Inspector (Observability UI) - High value for Developer Experience. Helps users debug their implementations. Medium complexity.
3. ~~Semantic Redundancy Elimination~~ — **IMPLEMENTED.** See `ce-core/src/redundancy.ts` and `python/context_engineering/redundancy.py`.
4. ~~Distributed Memory Stores~~ — **IMPLEMENTED.** Redis and PostgreSQL stores available in both TypeScript and Python.
5. Universal Context Proxy - Very high value, but high complexity and architectural shift. Best saved for when the core algorithms are hardened and adopted.
