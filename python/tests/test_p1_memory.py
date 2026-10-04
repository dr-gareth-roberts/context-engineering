"""Regression tests for P1 memory-store bugs (Python parity with ce-memory)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time

import pytest

from context_engineering.memory import FileStore, MemoryItem, SqliteStore


def _item(item_id: str, **kwargs) -> MemoryItem:
    return MemoryItem(
        id=item_id, content=f"content {item_id}", createdAt="2026-01-01T00:00:00Z", **kwargs
    )


class TestFileStoreLocking:
    def test_does_not_steal_lock_owned_by_live_process(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "live.jsonl")
            lock = path + ".lock"
            with open(lock, "w") as f:
                json.dump({"pid": os.getpid(), "nonce": "live-owner"}, f)
            old = time.time() - 60
            os.utime(lock, (old, old))

            store = FileStore(path, lock_timeout=0.1, stale_lock_age=0.01)
            with pytest.raises(TimeoutError):
                store.put(_item("blocked"))
            with open(lock) as f:
                assert json.load(f)["nonce"] == "live-owner"

    def test_breaks_lock_of_dead_process(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "dead.jsonl")
            lock = path + ".lock"
            with open(lock, "w") as f:
                # PID 2**22 + 12345 is far above any real PID on macOS/Linux.
                json.dump({"pid": 2**22 + 12345, "nonce": "dead-owner"}, f)

            store = FileStore(path, lock_timeout=1.0, stale_lock_age=3600)
            store.put(_item("ok"))
            assert store.get("ok") is not None
            assert not os.path.exists(lock)

    def test_contending_instances_do_not_lose_writes(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "contended.jsonl")
            # stale_lock_age=0 makes every lock look stale by mtime: the old
            # mtime-only check let writers steal each other's locks.
            a = FileStore(path, lock_timeout=10.0, stale_lock_age=0)
            b = FileStore(path, lock_timeout=10.0, stale_lock_age=0)

            def writer(store: FileStore, prefix: str) -> None:
                for i in range(15):
                    store.put(_item(f"{prefix}{i}"))

            threads = [
                threading.Thread(target=writer, args=(a, "a")),
                threading.Thread(target=writer, args=(b, "b")),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            ids = {i.id for i in FileStore(path).query()}
            assert len(ids) == 30
            leftovers = [f for f in os.listdir(d) if f != "contended.jsonl"]
            assert leftovers == []


class TestSqliteStoreFields:
    def test_round_trips_links(self):
        with tempfile.TemporaryDirectory() as d:
            store = SqliteStore(os.path.join(d, "m.db"))
            store.put(_item("x", links=["a", "b"], isSummary=True, embedding=[0.5, 1.0]))
            got = store.get("x")
            assert got is not None
            assert got.links == ["a", "b"]
            assert got.is_summary is True
            assert got.embedding == [0.5, 1.0]
            assert [i.links for i in store.query()] == [["a", "b"]]

    def test_migrates_old_schema(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "old.db")
            conn = sqlite3.connect(db)
            conn.execute(
                """CREATE TABLE memory_items (
                    id TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT, last_accessed_at TEXT, salience REAL, ttl_seconds INTEGER,
                    is_summary INTEGER DEFAULT 0, embedding_json TEXT, metadata_json TEXT
                )"""
            )
            conn.execute(
                "INSERT INTO memory_items (id, content, created_at) VALUES ('old', 'legacy', '2026-01-01T00:00:00Z')"
            )
            conn.commit()
            conn.close()

            store = SqliteStore(db)
            legacy = store.get("old")
            assert legacy is not None and legacy.links == []
            store.put(_item("new", links=["old"]))
            new = store.get("new")
            assert new is not None and new.links == ["old"]
