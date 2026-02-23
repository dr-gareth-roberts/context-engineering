import os
import tempfile
import pytest
from datetime import datetime, timezone
from context_engineering.memory import InMemoryStore, FileStore, SqliteStore, MemoryItem, MemoryQuery


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class TestInMemoryStore:
    def test_put_and_get(self):
        store = InMemoryStore()
        items = store.put(MemoryItem(id="a", content="Hello", createdAt=_now_iso()))
        assert len(items) == 1
        fetched = store.get("a")
        assert fetched is not None
        assert fetched.content == "Hello"

    def test_get_missing(self):
        store = InMemoryStore()
        assert store.get("nonexistent") is None

    def test_batch_put(self):
        store = InMemoryStore()
        items = store.put([
            MemoryItem(id="a", content="First", createdAt=_now_iso()),
            MemoryItem(id="b", content="Second", createdAt=_now_iso()),
        ])
        assert len(items) == 2
        assert store.get("a") is not None
        assert store.get("b") is not None

    def test_forget(self):
        store = InMemoryStore()
        store.put(MemoryItem(id="a", content="Hello", createdAt=_now_iso()))
        assert store.forget("a") is True
        assert store.get("a") is None

    def test_forget_missing(self):
        store = InMemoryStore()
        assert store.forget("nope") is False

    def test_query_limit(self):
        store = InMemoryStore()
        store.put([
            MemoryItem(id="a", content="1", createdAt=_now_iso()),
            MemoryItem(id="b", content="2", createdAt=_now_iso()),
            MemoryItem(id="c", content="3", createdAt=_now_iso()),
        ])
        results = store.query(MemoryQuery(limit=2))
        assert len(results) == 2

    def test_upsert(self):
        store = InMemoryStore()
        store.put(MemoryItem(id="a", content="V1", createdAt=_now_iso()))
        store.put(MemoryItem(id="a", content="V2", createdAt=_now_iso()))
        assert store.get("a").content == "V2"


class TestFileStore:
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "memory.jsonl")
            store = FileStore(path)
            store.put(MemoryItem(id="f1", content="Persisted", createdAt=_now_iso()))
            fetched = store.get("f1")
            assert fetched is not None
            assert fetched.content == "Persisted"

    def test_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "memory.jsonl")
            store1 = FileStore(path)
            store1.put(MemoryItem(id="f1", content="Data", createdAt=_now_iso()))
            store2 = FileStore(path)
            assert store2.get("f1").content == "Data"


    def test_corrupted_json_recovery(self):
        """FileStore skips corrupted JSON lines instead of crashing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "corrupted.jsonl")
            good_item = MemoryItem(id="good", content="Valid", createdAt=_now_iso())
            with open(path, "w") as f:
                f.write(good_item.model_dump_json(by_alias=True) + "\n")
                f.write("{broken json\n")
                f.write('{"also": "not a memory item"}\n')
            store = FileStore(path)
            results = store.query()
            assert len(results) == 1
            assert results[0].id == "good"

    def test_whitespace_only_lines(self):
        """FileStore handles files with whitespace-only lines."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "whitespace.jsonl")
            with open(path, "w") as f:
                f.write("\n  \n\n  \n")
            store = FileStore(path)
            assert store.query() == []

    def test_bare_filename(self):
        """FileStore handles bare filenames without directory component."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Use chdir to test bare filename behavior
            old_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                store = FileStore("bare.jsonl")
                store.put(MemoryItem(id="b1", content="Bare", createdAt=_now_iso()))
                assert store.get("b1").content == "Bare"
            finally:
                os.chdir(old_cwd)

    def test_thread_safety(self):
        """FileStore handles concurrent writes from multiple threads."""
        import threading

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "threaded.jsonl")
            store = FileStore(path)
            errors = []

            def writer(thread_id):
                try:
                    for i in range(5):
                        store.put(MemoryItem(
                            id=f"t{thread_id}-{i}",
                            content=f"Thread {thread_id} item {i}",
                            createdAt=_now_iso(),
                        ))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Thread errors: {errors}"
            results = store.query()
            assert len(results) == 20  # 4 threads * 5 items

    def test_forget_persists(self):
        """Forget removes item and persists the change."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "forget.jsonl")
            store = FileStore(path)
            store.put([
                MemoryItem(id="keep", content="Keep me", createdAt=_now_iso()),
                MemoryItem(id="remove", content="Remove me", createdAt=_now_iso()),
            ])
            assert store.forget("remove") is True
            # Verify persistence by reloading
            store2 = FileStore(path)
            assert store2.get("remove") is None
            assert store2.get("keep") is not None


class TestSqliteStore:
    def test_put_and_get(self):
        store = SqliteStore(":memory:")
        store.put(MemoryItem(id="s1", content="SQLite", createdAt=_now_iso()))
        assert store.get("s1").content == "SQLite"

    def test_upsert(self):
        store = SqliteStore(":memory:")
        store.put(MemoryItem(id="s1", content="V1", createdAt=_now_iso()))
        store.put(MemoryItem(id="s1", content="V2", createdAt=_now_iso()))
        assert store.get("s1").content == "V2"

    def test_batch_insert(self):
        store = SqliteStore(":memory:")
        items = store.put([
            MemoryItem(id="b1", content="First", createdAt=_now_iso()),
            MemoryItem(id="b2", content="Second", createdAt=_now_iso()),
        ])
        assert len(items) == 2
