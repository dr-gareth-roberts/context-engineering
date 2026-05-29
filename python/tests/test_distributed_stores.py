from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_engineering.memory import MemoryItem, MemoryQuery
from context_engineering.postgres_store import PostgresMemoryStore
from context_engineering.redis_store import RedisMemoryStore


@pytest.fixture
def mock_redis():
    with patch("context_engineering.redis_store.redis") as mock_redis_mod:
        mock_client = MagicMock()

        mock_pipeline = AsyncMock()
        mock_pipeline.__aenter__.return_value = mock_pipeline
        mock_pipeline.__aexit__.return_value = None
        mock_pipeline.set = MagicMock()
        mock_pipeline.execute = AsyncMock()
        mock_client.pipeline.return_value = mock_pipeline

        # Async methods
        mock_client.get = AsyncMock()
        mock_client.mget = AsyncMock()
        mock_client.scan = AsyncMock()

        mock_redis_mod.from_url.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_asyncpg():
    with patch("context_engineering.postgres_store.asyncpg") as mock_pg:
        mock_pool = MagicMock()
        mock_conn = AsyncMock()

        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_pool.acquire.return_value.__aexit__.return_value = None
        mock_pool.close = AsyncMock()

        mock_pg.create_pool = AsyncMock(return_value=mock_pool)
        yield mock_conn


@pytest.mark.asyncio
async def test_redis_store_edge_cases(mock_redis):
    store = RedisMemoryStore("redis://fake")

    # Test empty array to aput
    res = await store.aput([])
    assert res == []

    # Test negative TTL
    item = MemoryItem(id="neg", content="data", created_at="2023-01-01T00:00:00Z", ttl_seconds=-10)
    await store.aput([item])
    mock_pipeline = mock_redis.pipeline.return_value
    # Should call set without EX because ttl_seconds <= 0
    mock_pipeline.set.assert_called_with("ce_memory:neg", item.model_dump_json(by_alias=True))

    # Test aget when not found
    mock_redis.get.return_value = None
    assert await store.aget("missing") is None

    # Test aquery returns empty when no keys (scan returns cursor=0 and empty batch)
    mock_redis.scan.return_value = (0, [])
    assert await store.aquery() == []

    # Test aquery with scan returning keys
    mock_redis.scan.return_value = (0, ["ce_memory:1"])
    item_json = MemoryItem(
        id="1", content="data", created_at="2023-01-01T00:00:00Z"
    ).model_dump_json(by_alias=True)
    mock_redis.mget.return_value = [
        item_json,
        None,
    ]  # simulating mget returning a None for a deleted key

    res = await store.aquery(MemoryQuery())
    assert len(res) == 1
    assert res[0].id == "1"


@pytest.mark.asyncio
async def test_postgres_store_edge_cases(mock_asyncpg):
    store = PostgresMemoryStore("postgresql://fake")

    # Test empty aput
    res = await store.aput([])
    assert res == []

    # Test aput with vector (embedding)
    item = MemoryItem(
        id="vec", content="data", created_at="2023-01-01T00:00:00Z", embedding=[0.1, 0.2, 0.3]
    )
    await store.aput([item])

    # Check if the query formed handles the array properly by casting to string
    call_args = mock_asyncpg.execute.call_args[0]
    assert any("[0.1,0.2,0.3]" in str(arg) for arg in call_args)

    # Test aget when not found
    mock_asyncpg.fetchrow.return_value = None
    assert await store.aget("missing") is None

    # Test aget with weird embedding format in DB
    mock_asyncpg.fetchrow.return_value = {
        "id": "1",
        "content": "data",
        "created_at": "2023-01-01T00:00:00Z",
        "updated_at": None,
        "last_accessed_at": None,
        "salience": 1.0,
        "ttl_seconds": None,
        "is_summary": False,
        "metadata": "{}",
        "embedding": "[invalid json]",  # Simulate corrupted DB state
    }
    fetched = await store.aget("1")
    assert fetched is not None
    assert fetched.embedding is None  # Should swallow invalid json and return None for embedding

    # Test aquery SQL construction with multiple clauses
    mock_asyncpg.fetch.return_value = []
    q = MemoryQuery(text="test", limit=5, vector=[1.0, 2.0])
    await store.aquery(q)

    call_args = mock_asyncpg.fetch.call_args[0]
    sql = call_args[0]
    # Check if text, order by vector, and limit clauses were added
    assert "ILIKE $1" in sql
    assert "ORDER BY embedding <=> $2::vector" in sql
    assert "LIMIT $3" in sql
    assert "%test%" in call_args
    assert "[1.0,2.0]" in call_args
    assert 10 in call_args  # Limit is multiplied by 2 internally


def _pg_row(
    *,
    id: str,
    content: str,
    created_at: str,
    salience: float,
):
    """Build a fake asyncpg row dict matching the aquery SELECT columns."""
    return {
        "id": id,
        "content": content,
        "created_at": created_at,
        "updated_at": None,
        "last_accessed_at": None,
        "salience": salience,
        "ttl_seconds": None,
        "is_summary": False,
        "metadata": "{}",
        "embedding": None,
    }


@pytest.mark.asyncio
async def test_postgres_vectorless_limit_not_pushed_to_sql(mock_asyncpg):
    """Regression: a vector-less limited query must NOT push a SQL LIMIT.

    Previously the SQL fetched only the newest ``limit*2`` rows by created_at
    before Python re-ranked by hybrid (salience-dominated) score, so a
    high-salience but old memory outside that window could never appear. The
    fix fetches the full candidate set and lets _apply_query apply the limit
    after ranking, matching the in-memory / Redis / SQLite / file backends.
    """
    store = PostgresMemoryStore("postgresql://fake")

    mock_asyncpg.fetch.return_value = []
    await store.aquery(MemoryQuery(limit=5))

    sql = mock_asyncpg.fetch.call_args[0][0]
    # No SQL LIMIT and no recency pre-filter for vector-less queries.
    assert "LIMIT" not in sql
    assert "ORDER BY created_at DESC" not in sql


@pytest.mark.asyncio
async def test_postgres_vectorless_returns_high_salience_old_item(mock_asyncpg):
    """Parity: with the full set fetched, a high-salience OLD memory must be
    returned for a vector-less limited query, mirroring the in-memory backend.

    With alpha=0.0 and no vector, the hybrid score reduces to salience, so the
    old high-salience item must outrank the newer low-salience ones.
    """
    limit = 2
    rows = [
        _pg_row(
            id="old-high",
            content="old but important",
            created_at="2000-01-01T00:00:00+00:00",
            salience=0.99,
        ),
    ]
    # 2*limit + 1 newer, low-salience rows that would have crowded out the old
    # high-salience item under the previous recency-based prefilter.
    for n in range(2 * limit + 1):
        rows.append(
            _pg_row(
                id=f"new-low-{n}",
                content=f"recent filler {n}",
                created_at=f"2024-01-0{n + 1}T00:00:00+00:00",
                salience=0.10,
            )
        )
    mock_asyncpg.fetch.return_value = rows

    store = PostgresMemoryStore("postgresql://fake")
    result = await store.aquery(MemoryQuery(limit=limit, alpha=0.0))

    returned_ids = [item.id for item in result]
    assert "old-high" in returned_ids
    assert len(result) == limit
    # The old high-salience item should rank first.
    assert returned_ids[0] == "old-high"
