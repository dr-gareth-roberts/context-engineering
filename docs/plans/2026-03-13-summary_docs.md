# Feature Summary: Semantic Redundancy & Distributed Memory Stores

_Date: March 13, 2026_

## Feature 3: Semantic Redundancy Elimination

### Description

Implemented a pre-processing phase that detects and merges context items containing highly similar information before they consume the token budget. This prevents "context bloat" and model confusion.

### Implementation Details

- **Protocol:** Added an `EmbeddingProvider` interface to both TS and Python.
- **Math:** Implemented exact `cosineSimilarity` mathematical comparisons.
- **Clustering:** Added an `eliminateRedundancy` loop that uses agglomerative clustering. If vectors share a cosine similarity higher than the given `similarityThreshold` (e.g. 0.92), they are clustered.
- **Resolution:** Uses a configurable strategy (e.g., `recent` or `summarize`) to pick the surviving item. Ties are resolved by the secondary `priority` score.
- **Integration:** Wired seamlessly into `packAsync` (TS) and `pack_async` (Python).

### Edge Cases Handled & Tested

- Zero-magnitude vector division without producing `NaN`/`Infinity`.
- Negative cosine similarities (perfectly opposite vectors).
- Missing vector grace handling and empty item arrays.
- Perfect collision tie-breaking.

---

## Feature 4: Distributed Memory Stores

### Description

Expanded the memory abstraction to support remote, high-scale datastores, unlocking the ability for the context-engineering toolkit to scale to multi-user, stateless, production-grade deployments.

### Implementation Details

- **Redis (`RedisStore` / `RedisMemoryStore`):**
  - Built for Node (`ioredis`) and Python (`redis.asyncio`).
  - Implemented high-performance batched caching via `pipeline()`.
  - Added native dynamic mapping of `ttlSeconds` to `EX` expirations in the Redis cluster.
- **Postgres (`PostgresMemoryStore`):**
  - Built for Python (`asyncpg`).
  - Added self-initializing database schemas (`CREATE EXTENSION IF NOT EXISTS vector;` for `pgvector`).
  - Built dynamic `aquery()` SQL query generators combining `ILIKE`, `ORDER BY embedding <=> :vector`, and `LIMIT` seamlessly.

### Edge Cases Handled & Tested

- **TTL Extension:** Simply reading (`get()`) an item resets/extends its TTL lease on the Redis cluster automatically.
- **Negative TTLs:** Protected against Redis crashing when fed invalid `EX -10` commands.
- **Corrupted SQL Data:** If the `embedding` JSON column gets corrupted, the store gracefully swallows the JSON decode error and continues to return the row with `embedding: None` instead of breaking the entire app.
