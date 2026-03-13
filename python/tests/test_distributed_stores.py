from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_engineering.memory import MemoryItem, MemoryQuery
from context_engineering.postgres_store import PostgresMemoryStore
from context_engineering.redis_store import RedisMemoryStore


@pytest.fixture
def mock_redis():
    with patch('context_engineering.redis_store.redis') as mock_redis_mod:
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
        mock_client.keys = AsyncMock()

        mock_redis_mod.from_url.return_value = mock_client
        yield mock_client

@pytest.fixture
def mock_asyncpg():
    with patch('context_engineering.postgres_store.asyncpg') as mock_pg:
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
    mock_pipeline.set.assert_called_with('ce_memory:neg', item.model_dump_json(by_alias=True))

    # Test aget when not found
    mock_redis.get.return_value = None
    assert await store.aget("missing") is None

    # Test aquery returns empty when no keys
    mock_redis.keys.return_value = []
    assert await store.aquery() == []

    # Test aquery with malformed JSON skips silently or we expect the standard apply_query flow
    # Assuming mget returns the correct structure
    mock_redis.keys.return_value = ["ce_memory:1"]
    item_json = MemoryItem(id="1", content="data", created_at="2023-01-01T00:00:00Z").model_dump_json(by_alias=True)
    mock_redis.mget.return_value = [item_json, None] # simulating mget returning a None for a deleted key

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
    item = MemoryItem(id="vec", content="data", created_at="2023-01-01T00:00:00Z", embedding=[0.1, 0.2, 0.3])
    await store.aput([item])

    # Check if the query formed handles the array properly by casting to string
    call_args = mock_asyncpg.execute.call_args[0]
    assert any("[0.1,0.2,0.3]" in str(arg) for arg in call_args)

    # Test aget when not found
    mock_asyncpg.fetchrow.return_value = None
    assert await store.aget("missing") is None

    # Test aget with weird embedding format in DB
    mock_asyncpg.fetchrow.return_value = {
        'id': '1', 'content': 'data', 'created_at': '2023-01-01T00:00:00Z',
        'updated_at': None, 'last_accessed_at': None, 'salience': 1.0,
        'ttl_seconds': None, 'is_summary': False, 'metadata': "{}",
        'embedding': "[invalid json]" # Simulate corrupted DB state
    }
    fetched = await store.aget("1")
    assert fetched is not None
    assert fetched.embedding is None # Should swallow invalid json and return None for embedding

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
    assert 10 in call_args # Limit is multiplied by 2 internally
