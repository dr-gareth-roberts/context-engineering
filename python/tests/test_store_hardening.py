"""Regression tests for production-hardening fixes in the py-stores group.

Each test fails against the pre-fix code and passes after the fix:
  - FileStore cross-process reload (memory.py)
  - Postgres pool lazy-init lock (postgres_store.py)
  - Postgres NULL/JSON-null metadata coalescing (postgres_store.py)
  - Redis read-time TTL preservation (redis_store.py)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_engineering.memory import FileStore, MemoryItem, MemoryQuery
from context_engineering.postgres_store import PostgresMemoryStore
from context_engineering.redis_store import RedisMemoryStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestFileStoreCrossProcessReload:
    def test_concurrent_writer_item_survives(self):
        """A second process's committed write must not be clobbered by a stale snapshot.

        Mirrors the multi-process repro: instance A loads the file, instance B
        (simulating another process) appends an item and persists, then A writes
        again. Before the fix, A never re-reads B's change and os.replace silently
        loses B's item. After the fix, A reloads under the lock when the file's
        mtime changed and B's item survives.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "shared.jsonl")
            store_a = FileStore(path)
            store_b = FileStore(path)

            # A loads the file (empty) and caches its snapshot.
            store_a.put(MemoryItem(id="from_a", content="A", createdAt=_now_iso()))

            # B (another process) commits a new item.
            store_b.put(MemoryItem(id="from_b", content="B", createdAt=_now_iso()))

            # Guarantee a distinct mtime even on coarse-granularity filesystems
            # so the reload is exercised deterministically (real processes would
            # differ in wall-clock time across writes).
            future = time.time() + 5
            os.utime(path, (future, future))

            # A writes again. It must first pick up B's committed item.
            store_a.put(MemoryItem(id="from_a2", content="A2", createdAt=_now_iso()))

            # Independent reader sees all three items, proving B was not clobbered.
            reader = FileStore(path)
            ids = {item.id for item in reader.query(MemoryQuery(include_expired=True))}
            assert ids == {"from_a", "from_b", "from_a2"}

    def test_forget_by_other_process_not_resurrected(self):
        """An item deleted by another process must not reappear after reload."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "shared_forget.jsonl")
            store_a = FileStore(path)
            store_b = FileStore(path)

            store_a.put(MemoryItem(id="doomed", content="x", createdAt=_now_iso()))
            # A has it cached.
            assert store_a.get("doomed") is not None

            # B deletes it.
            store_b.forget("doomed")

            future = time.time() + 5
            os.utime(path, (future, future))

            # A writes an unrelated item; the reset-before-reload must drop "doomed".
            store_a.put(MemoryItem(id="other", content="y", createdAt=_now_iso()))

            reader = FileStore(path)
            ids = {item.id for item in reader.query(MemoryQuery(include_expired=True))}
            assert ids == {"other"}


class TestPostgresPoolInitLock:
    @pytest.mark.asyncio
    async def test_pool_created_once_under_concurrent_cold_start(self):
        """Concurrent first requests must create exactly one pool (no orphaned pool)."""
        with patch("context_engineering.postgres_store.asyncpg") as mock_pg:
            gate = asyncio.Event()
            call_count = 0

            mock_pool = MagicMock()
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_pool.acquire.return_value.__aexit__.return_value = None

            async def slow_create_pool(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                # Suspend so a second coroutine can race into init() before assignment.
                await gate.wait()
                return mock_pool

            mock_pg.create_pool = AsyncMock(side_effect=slow_create_pool)

            store = PostgresMemoryStore("postgresql://fake")

            task_a = asyncio.create_task(store._get_pool())
            task_b = asyncio.create_task(store._get_pool())

            # Let both tasks reach the create_pool suspension point.
            await asyncio.sleep(0)
            await asyncio.sleep(0)

            gate.set()
            pool_a = await task_a
            pool_b = await task_b

            assert call_count == 1, f"create_pool awaited {call_count} times, expected 1"
            assert pool_a is pool_b is mock_pool


class TestPostgresNullMetadata:
    @pytest.fixture
    def mock_asyncpg(self):
        with patch("context_engineering.postgres_store.asyncpg") as mock_pg:
            mock_pool = MagicMock()
            mock_conn = AsyncMock()
            mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
            mock_pool.acquire.return_value.__aexit__.return_value = None
            mock_pool.close = AsyncMock()
            mock_pg.create_pool = AsyncMock(return_value=mock_pool)
            yield mock_conn

    @pytest.mark.asyncio
    async def test_aget_handles_sql_null_metadata(self, mock_asyncpg):
        """A row with SQL NULL metadata must yield an item with an empty dict."""
        mock_asyncpg.fetchrow.return_value = {
            "id": "1",
            "content": "data",
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": None,
            "last_accessed_at": None,
            "salience": 1.0,
            "ttl_seconds": None,
            "is_summary": False,
            "metadata": None,  # SQL NULL
            "embedding": None,
        }
        store = PostgresMemoryStore("postgresql://fake")
        item = await store.aget("1")
        assert item is not None
        assert item.metadata == {}

    @pytest.mark.asyncio
    async def test_aget_handles_json_null_metadata(self, mock_asyncpg):
        """A stored JSON null ('null' text) must coalesce to an empty dict."""
        mock_asyncpg.fetchrow.return_value = {
            "id": "2",
            "content": "data",
            "created_at": "2023-01-01T00:00:00Z",
            "updated_at": None,
            "last_accessed_at": None,
            "salience": 1.0,
            "ttl_seconds": None,
            "is_summary": False,
            "metadata": "null",  # JSON null arrives as text
            "embedding": None,
        }
        store = PostgresMemoryStore("postgresql://fake")
        item = await store.aget("2")
        assert item is not None
        assert item.metadata == {}

    @pytest.mark.asyncio
    async def test_aquery_handles_null_metadata(self, mock_asyncpg):
        """aquery must also tolerate a NULL-metadata row."""
        mock_asyncpg.fetch.return_value = [
            {
                "id": "3",
                "content": "data",
                "created_at": "2023-01-01T00:00:00Z",
                "updated_at": None,
                "last_accessed_at": None,
                "salience": 1.0,
                "ttl_seconds": None,
                "is_summary": False,
                "metadata": None,  # SQL NULL
                "embedding": None,
            }
        ]
        store = PostgresMemoryStore("postgresql://fake")
        results = await store.aquery(MemoryQuery())
        assert len(results) == 1
        assert results[0].metadata == {}


class TestRedisReadPreservesTtl:
    @pytest.fixture
    def mock_redis(self):
        with patch("context_engineering.redis_store.redis") as mock_redis_mod:
            mock_client = MagicMock()
            mock_client.get = AsyncMock()
            mock_client.set = AsyncMock()
            mock_redis_mod.from_url.return_value = mock_client
            yield mock_client

    @pytest.mark.asyncio
    async def test_aget_uses_keepttl_and_never_resets_expiry(self, mock_redis):
        """Reads must preserve the native TTL (keepttl) and never pass ex=."""
        item = MemoryItem(
            id="hot", content="data", created_at="2023-01-01T00:00:00Z", ttl_seconds=3600
        )
        mock_redis.get.return_value = item.model_dump_json(by_alias=True)

        store = RedisMemoryStore("redis://fake")
        result = await store.aget("hot")

        assert result is not None
        mock_redis.set.assert_awaited_once()
        _, kwargs = mock_redis.set.call_args
        assert kwargs.get("keepttl") is True
        # The sliding-TTL bug re-set ex=ttl_seconds on every read; that must be gone.
        assert "ex" not in kwargs

    def test_redis_set_actually_accepts_keepttl(self):
        """Guard against a swallowed kwarg: the real redis-py set() must accept keepttl.

        The AsyncMock above accepts any kwarg, so it cannot catch a typo or a
        removed parameter. This asserts keepttl is a genuine parameter of the
        installed redis-py client (introduced in redis-py 3.5; pin is >=5.0.0).
        """
        import inspect

        redis_asyncio = pytest.importorskip("redis.asyncio")
        params = inspect.signature(redis_asyncio.Redis.set).parameters
        assert "keepttl" in params
