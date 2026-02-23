import os
import tempfile
from datetime import datetime, timedelta

from context_engineering.memory import InMemoryStore, FileStore, SqliteStore, MemoryItem, MemoryQuery


def test_in_memory_store():
    store = InMemoryStore()
    store.put(MemoryItem(id="a", content="hello", createdAt=datetime.utcnow().isoformat()))
    assert store.get("a") is not None


def test_file_store_roundtrip():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "memory.jsonl")
        store = FileStore(path)
        store.put(MemoryItem(id="b", content="world", createdAt=datetime.utcnow().isoformat()))
        assert store.get("b") is not None


def test_sqlite_ttl_expiry():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "memory.sqlite")
        store = SqliteStore(path)
        past = (datetime.utcnow() - timedelta(seconds=10)).isoformat()
        store.put(MemoryItem(id="c", content="expired", createdAt=past, ttlSeconds=1))
        results = store.query(MemoryQuery(now=int(datetime.utcnow().timestamp() * 1000)))
        assert len(results) == 0
