# Roadmap 06: Distributed Memory Stores

> **Status: IMPLEMENTED** — Redis and PostgreSQL memory stores are available. TypeScript: `RedisStore` in `ce-memory`. Python: `RedisMemoryStore` and `PostgresMemoryStore` in `context_engineering`. Install with `pip install context-engineering-toolkit[redis]` or `pip install context-engineering-toolkit[postgres]`.

## Objective

Scale the `context-engineering` toolkit from single-script demos to multi-user, production-grade applications.

## 1. Redis Store (`RedisMemoryStore`)

- **Use Case:** Ephemeral session memory, extremely low latency.
- **Implementation:**
  - Use Redis Hashes to store `MemoryItems`.
  - Use Redis TTL for automatic expiration (matching the `ttlSeconds` field).
  - Support Redis Search (RediSearch) for basic priority/metadata filtering.

## 2. PostgreSQL / pgvector Store (`PostgresMemoryStore`)

- **Use Case:** Long-term relational memory + semantic search.
- **Implementation:**
  - Single table: `ce_memory_items`.
  - Column `embedding` of type `vector(N)`.
  - Hybrid Query: `SELECT * FROM ce_memory_items WHERE agent_id = :id ORDER BY (salience * :w1 + recency * :w2) DESC`.

## 3. Remote Sync

- **Feature:** A `HybridStore` that keeps a local SQLite cache for speed but syncs asynchronously to a central Postgres database.

## Implementation Plan

1.  Define a stable `BaseStore` interface in `packages/ce-memory`.
2.  Implement `RedisStore` using `ioredis` (TS) and `redis-py` (Python).
3.  Implement `PostgresStore` using `pgvector`.

## Success Criteria

- The `AgentContextManager` can be initialized with a remote Redis URL and handle 10,000+ concurrent sessions.
