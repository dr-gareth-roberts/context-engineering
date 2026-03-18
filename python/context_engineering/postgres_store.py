import json
import logging
from typing import Any, List, Optional, cast

from .memory import MemoryItem, MemoryQuery, MemoryStore, _normalize, _now_iso

try:
    import asyncpg  # pyright: ignore[reportMissingImports]
except ImportError:
    asyncpg = None

Pool = Any

logger = logging.getLogger(__name__)


class PostgresMemoryStore(MemoryStore):
    def __init__(self, dsn: str, pool_size: int = 10):
        if asyncpg is None:
            raise ImportError(
                "asyncpg package is required for PostgresMemoryStore. Install it with `pip install asyncpg`."
            )
        self.dsn = dsn
        self.pool_size = pool_size
        self._pool: Pool | None = None

    def _require_asyncpg(self) -> Any:
        if asyncpg is None:
            raise ImportError(
                "asyncpg package is required for PostgresMemoryStore. Install it with `pip install asyncpg`."
            )
        return cast(Any, asyncpg)

    async def _get_pool(self) -> Pool:
        if self._pool is None:
            await self.init()
        assert self._pool is not None
        return self._pool

    async def init(self):
        if not self._pool:
            asyncpg_mod = self._require_asyncpg()
            self._pool = await asyncpg_mod.create_pool(
                dsn=self.dsn, min_size=1, max_size=self.pool_size
            )

        async with self._pool.acquire() as conn:
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            except Exception as exc:
                logger.warning(
                    "Could not create pgvector extension (vector search will be unavailable): %s",
                    exc,
                )

            # Create table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ce_memory_items (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT,
                    last_accessed_at TEXT,
                    salience REAL,
                    ttl_seconds INTEGER,
                    is_summary BOOLEAN DEFAULT FALSE,
                    metadata JSONB
                );
            """)

            # Check if embedding column exists, if not try to add it
            try:
                await conn.execute("""
                    ALTER TABLE ce_memory_items ADD COLUMN embedding vector(1536);
                """)
            except Exception:
                # Column likely already exists, or vector type unsupported.
                pass

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def aput(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        items = item if isinstance(item, list) else [item]
        normalized = [_normalize(e) for e in items]

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for e in normalized:
                embedding_val = e.embedding if e.embedding else None

                query = """
                    INSERT INTO ce_memory_items (
                        id, content, created_at, updated_at, last_accessed_at,
                        salience, ttl_seconds, is_summary, metadata, embedding
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        updated_at = EXCLUDED.updated_at,
                        last_accessed_at = EXCLUDED.last_accessed_at,
                        salience = EXCLUDED.salience,
                        ttl_seconds = EXCLUDED.ttl_seconds,
                        is_summary = EXCLUDED.is_summary,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding;
                """
                # Using a generic approach to pass embeddings. asyncpg pgvector integration might be needed for native vectors.
                # If native pgvector isn't registered, we can pass a string representation: f"[{','.join(map(str, embedding_val))}]"
                if embedding_val:
                    embedding_val = f"[{','.join(map(str, embedding_val))}]"

                await conn.execute(
                    query,
                    e.id,
                    e.content,
                    e.created_at,
                    e.updated_at,
                    e.last_accessed_at,
                    e.salience,
                    e.ttl_seconds,
                    e.is_summary,
                    json.dumps(e.metadata),
                    embedding_val,
                )
        return normalized

    async def aget(self, item_id: str) -> Optional[MemoryItem]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # Update last accessed
            now_iso = _now_iso()
            await conn.execute(
                "UPDATE ce_memory_items SET last_accessed_at = $1 WHERE id = $2", now_iso, item_id
            )

            # Since vector column isn't always present/supported identically, we fetch all except embedding or cast embedding to text.
            row = await conn.fetchrow(
                """
                SELECT id, content, created_at, updated_at, last_accessed_at,
                       salience, ttl_seconds, is_summary, metadata, embedding::text
                FROM ce_memory_items WHERE id = $1
            """,
                item_id,
            )

            if not row:
                return None

            embedding_str = row["embedding"]
            embedding_list = None
            if embedding_str:
                try:
                    # '[0.1, 0.2, ...]'
                    embedding_list = json.loads(embedding_str)
                except Exception:
                    pass

            return MemoryItem(
                id=row["id"],
                content=row["content"],
                createdAt=row["created_at"],
                updatedAt=row["updated_at"],
                lastAccessedAt=now_iso,
                salience=row["salience"],
                ttlSeconds=row["ttl_seconds"],
                isSummary=row["is_summary"],
                metadata=json.loads(row["metadata"])
                if isinstance(row["metadata"], str)
                else row["metadata"],
                embedding=embedding_list,
            )

    async def aquery(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        query = query or MemoryQuery()

        # Build SQL query dynamically
        base_sql = """
            SELECT id, content, created_at, updated_at, last_accessed_at,
                   salience, ttl_seconds, is_summary, metadata, embedding::text
            FROM ce_memory_items
            WHERE 1=1
        """

        args = []
        idx = 1

        if query.text:
            base_sql += f" AND content ILIKE ${idx}"
            args.append(f"%{query.text}%")
            idx += 1

        if not query.include_expired:
            # In PostgreSQL we can do basic time math, but for simplicity we rely on the memory.py python logic
            # if we wanted to be perfectly compatible. For now, we fetch a larger set and filter in Python.
            pass

        # Order by vector similarity if provided
        if query.vector:
            vec_str = f"[{','.join(map(str, query.vector))}]"
            base_sql += f" ORDER BY embedding <=> ${idx}::vector"
            args.append(vec_str)
            idx += 1
        elif query.limit:
            # Sort by created_at desc as a fallback
            base_sql += " ORDER BY created_at DESC"

        if query.limit:
            base_sql += f" LIMIT ${idx}"
            args.append(query.limit * 2)  # Fetch extra in case of TTL/salience dropping
            idx += 1

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(base_sql, *args)

        items = []
        for row in rows:
            embedding_str = row["embedding"]
            embedding_list = None
            if embedding_str:
                try:
                    embedding_list = json.loads(embedding_str)
                except Exception:
                    pass

            item = MemoryItem(
                id=row["id"],
                content=row["content"],
                createdAt=row["created_at"],
                updatedAt=row["updated_at"],
                lastAccessedAt=row["last_accessed_at"],
                salience=row["salience"],
                ttlSeconds=row["ttl_seconds"],
                isSummary=row["is_summary"],
                metadata=json.loads(row["metadata"])
                if isinstance(row["metadata"], str)
                else row["metadata"],
                embedding=embedding_list,
            )
            items.append(item)

        # Apply standard memory python filters (TTL, salience, etc)
        from .memory import _apply_query

        return _apply_query(items, query)

    async def aforget(self, item_id: str) -> bool:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute("DELETE FROM ce_memory_items WHERE id = $1", item_id)
            return int(status.split()[-1]) > 0

    def put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        raise NotImplementedError("PostgresMemoryStore is async-only. Use aput().")

    def get(self, item_id: str) -> Optional[MemoryItem]:
        raise NotImplementedError("PostgresMemoryStore is async-only. Use aget().")

    def query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        raise NotImplementedError("PostgresMemoryStore is async-only. Use aquery().")

    def forget(self, item_id: str) -> bool:
        raise NotImplementedError("PostgresMemoryStore is async-only. Use aforget().")
