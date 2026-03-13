# Future Features Implementation Plan

This document provides detailed implementation plans, architectures, and task breakdowns for the next five major features in the `context-engineering` roadmap.

---

## 1. Context Inspector (Observability UI)

**Goal:** Provide a visual debugging suite to inspect the "Context Packing" process, helping developers understand why specific items were included, compressed, or dropped.

### Architecture
- **Data Model:** We will expand the `TraceStep` schema to capture detailed scoring metrics, the specific reason for dropping an item, and any comparison/supersession events.
- **Frontend App:** The `ce-web-client` package will gain an `/inspect` route and new React components (`TraceTimeline`, `TokenBar`, `ItemDetailView`). 

### Task Breakdown
1. **Extend Trace Schema**
   - Update `schemas/context-trace.schema.json` and `packages/ce-core/src/types.ts` to include:
     ```ts
     interface TraceStep {
       metrics?: {
         priorityScore: number;
         recencyScore: number;
         salienceScore: number;
         finalRank: number;
       };
       reason?: "budget_exceeded" | "superseded" | "below_threshold";
       comparison?: { supersededById?: string; duplicateOfId?: string };
     }
     ```
   - Update the Python equivalent in `python/context_engineering/schemas/`.

2. **Instrument `pack()` Core Algorithm**
   - Modify `packages/ce-core/src/pack.ts` to record these detailed metrics when tracing is enabled.
   - Modify Python `core.py` to capture and emit these enriched trace steps.

3. **Develop Frontend Components (`packages/ce-web-client`)**
   - **Route Setup:** Add `/inspect` using standard React Router or `wouter`.
   - **`TraceTimeline`:** A vertical, chronologically or rank-ordered list showing items going through the packing funnel. 
   - **`TokenBar`:** A D3 or pure CSS/HTML progress bar showing the budget fill state, distinguishing between `usedTokens` and `reserveTokens`.
   - **`ItemDetailView`:** A drawer/modal that displays the raw content of a `ContextItem` along with the mathematical breakdown of its `score`.

4. **Interactive "What-If" Slider**
   - Implement a slider bound to `maxTokens`. 
   - When the slider is moved, re-run the `runPack()` algorithm in-browser and animate the UI to show items popping in or out of the context window.

---

## 2. Semantic Redundancy Elimination

**Goal:** Automatically detect and merge context items that contain the same information, preventing "context bloat" and model confusion.

### Architecture
We will introduce an `EmbeddingProvider` protocol and a `RedundancyEliminator` phase that runs *before* the greedy token packer. It calculates pairwise cosine similarity between context items and resolves duplicates based on configured strategies.

### Task Breakdown
1. **Define `EmbeddingProvider` Interfaces**
   - TS: `export interface EmbeddingProvider { embed(texts: string[]): Promise<number[][]>; }`
   - Python: `class EmbeddingProvider(Protocol): async def embed(self, texts: list[str]) -> list[list[float]]: ...`

2. **Implement Core `RedundancyEliminator` logic**
   - Implement agglomerative clustering based on a `similarity_threshold` (e.g., 0.90).
   - Create strategies:
     - `recent`: Keeps the item with the highest `recency` score, dropping the rest.
     - `summarize`: Uses an LLM to merge conflicting texts into a unified item.
   - For dropped duplicate items, add a `supersedes` or `duplicateOfId` reference to the surviving item to maintain trace auditability.

3. **Integrate into the Pipeline**
   - Add a `redundancyStrategy` option to `PackOptions`.
   - Execute the elimination phase prior to token estimation and budget allocation.

4. **Testing**
   - Create tests using hardcoded mock vectors to verify the clustering logic.
   - Verify that traces correctly reflect *why* an item was dropped (due to redundancy).

---

## 3. Distributed Memory Stores

**Goal:** Scale the `context-engineering` toolkit from single-script demos to multi-user, production-grade applications using Redis and Postgres.

### Architecture
We will implement robust plugins for `Redis` (ephemeral/TTL-based storage) and `Postgres` via `pgvector` (persistent/semantic search storage), adhering to the existing `BaseStore` abstraction.

### Task Breakdown
1. **Refine `BaseStore` interfaces**
   - Ensure all `put`, `get`, `query`, and `forget` methods are properly asynchronous in both TS and Python.
   - Add optional `limit`, `offset`, and `similarity_threshold` fields to `MemoryQuery`.

2. **Implement Redis Store**
   - **TS:** Use `ioredis`. **Python:** Use `redis-py`.
   - Map `MemoryItem` fields into Redis Hashes.
   - Use `EXPIRE` commands tied to the `ttlSeconds` property.
   - Use native Redis key scanning for querying (or RediSearch if available).

3. **Implement Postgres/pgvector Store**
   - **Python:** Use `asyncpg`. **TS:** Use `pg`.
   - Migration script to create `ce_memory_items` table with `id`, `agent_id`, `content`, `metadata` (JSONB), and `embedding` (vector).
   - Implement SQL hybrid search combining exact matches (e.g., `agent_id`) with vector similarity (`ORDER BY embedding <=> :vector`).

4. **Hybrid / Sync Store (Optional)**
   - Create a decorator store that instantly writes to local SQLite (for low latency reads) and queues an asynchronous background task to sync to Postgres.

---

## 4. Ecosystem Connectors (LangChain & LlamaIndex)

**Goal:** Enable developers to use the `context-engineering` toolkit within their existing agent frameworks with zero architectural changes.

### Architecture
Build subclass adapters that intercept memory loading or document post-processing steps within LangChain and LlamaIndex to apply budget-aware packing.

### Task Breakdown
1. **Project Configuration**
   - Update `python/pyproject.toml` with `[project.optional-dependencies]` for `langchain = ["langchain>=0.1.0"]` and `llamaindex = ["llama-index>=0.10.0"]`.

2. **LangChain Integration (`python/context_engineering/extensions/langchain.py`)**
   - Implement `CEContextMemory(BaseChatMemory)`.
   - Override `load_memory_variables(self, inputs)` to:
     - Fetch raw message history.
     - Convert LangChain messages to `ContextItems` (e.g., System Message = high priority, Human Message = high recency).
     - Run `pack()` against a defined token budget.
     - Return the pruned LangChain messages.
   
3. **LlamaIndex Integration (`python/context_engineering/extensions/llamaindex.py`)**
   - Implement `CEPostprocessor(BaseNodePostprocessor)`.
   - Override `_postprocess_nodes(self, nodes, query_bundle)` to:
     - Convert retrieved `NodeWithScore` objects into `ContextItems` using the retrieval score as `salience`.
     - Run `pack()` to fit exactly into the LLM context window.
     - Return the packed nodes.

4. **Testing**
   - Create extensive test suites using mocked LLM responses and validating that the output list of messages/nodes never exceeds the defined token budget limit.

---

## 5. Universal Context Proxy

**Goal:** Provide a "Context-as-a-Service" layer that acts as a drop-in replacement for OpenAI/Anthropic API endpoints, allowing any language to use the toolkit.

### Architecture
A standalone FastAPI server that intercepts `/v1/chat/completions` requests, parses a custom header (`X-CE-Budget`), runs the context engineering algorithms, and proxies the optimized prompt to the true upstream provider.

### Task Breakdown
1. **Server Setup**
   - Create a FastAPI application inside `python/context_engineering/proxy/app.py` or a new standalone TS package `packages/ce-proxy`. (We will default to Python/FastAPI for excellent async and streaming support).
   
2. **Request Interception**
   - Endpoint: `POST /v1/chat/completions`.
   - Parse the standard OpenAI JSON payload (`messages`, `model`, `stream`, etc.).
   - Extract `X-CE-Budget` and `X-CE-Session-Id` headers.

3. **Core Processing**
   - Map payload `messages` to `ContextItems`.
   - If `X-CE-Session-Id` is provided, automatically fetch historical context from a configured `MemoryStore`.
   - Run the `pack()` algorithm to optimize the messages down to the specified budget.
   
4. **Upstream Proxying**
   - Reconstruct the OpenAI compatible payload using only the packed messages.
   - Forward the request to the upstream provider using `httpx.AsyncClient`.
   
5. **Streaming Support**
   - If `stream=True` was requested, pass the incoming SSE stream directly back to the client using FastAPI's `StreamingResponse`.

6. **Deployment & Tooling**
   - Provide a `Dockerfile` for simple edge deployment.
   - Write integration tests acting as an HTTP client pointing to the proxy.
