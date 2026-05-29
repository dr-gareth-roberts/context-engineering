from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Generator, List, Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

from ._similarity import cosine_similarity as _cosine_similarity

logger = structlog.get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    content: str
    created_at: str = Field(alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")
    last_accessed_at: Optional[str] = Field(default=None, alias="lastAccessedAt")
    salience: Optional[float] = 1.0
    ttl_seconds: Optional[int] = Field(default=None, alias="ttlSeconds")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    is_summary: bool = Field(default=False, alias="isSummary")
    embedding: Optional[List[float]] = None
    links: List[str] = Field(default_factory=list)  # IDs of related memories


@dataclass
class MemoryQuery:
    text: Optional[str] = None
    vector: Optional[List[float]] = None  # For semantic search
    limit: Optional[int] = None
    min_score: float = 0.0
    include_expired: bool = False
    half_life_seconds: Optional[int] = None
    now: Optional[int] = None
    # Weights for hybrid ranking
    alpha: float = 0.5  # 1.0 = pure vector, 0.0 = pure salience


class MemoryStore:
    def put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        raise NotImplementedError

    def get(self, item_id: str) -> Optional[MemoryItem]:
        raise NotImplementedError

    def query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        raise NotImplementedError

    def forget(self, item_id: str) -> bool:
        raise NotImplementedError

    async def aput(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        return await asyncio.to_thread(self.put, item)

    async def aget(self, item_id: str) -> Optional[MemoryItem]:
        return await asyncio.to_thread(self.get, item_id)

    async def aquery(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        return await asyncio.to_thread(self.query, query)

    async def aforget(self, item_id: str) -> bool:
        return await asyncio.to_thread(self.forget, item_id)

    async def consolidate(
        self, summarizer: Callable[[str], Awaitable[str]], salience_threshold: float = 0.3
    ) -> int:
        raise NotImplementedError


def _normalize(item: MemoryItem | Dict[str, Any]) -> MemoryItem:
    if isinstance(item, MemoryItem):
        return item
    if "createdAt" not in item and "created_at" not in item:
        item["createdAt"] = _now_iso()
    if "updatedAt" not in item and "updated_at" not in item:
        item["updatedAt"] = item.get("createdAt")
    if "lastAccessedAt" not in item and "last_accessed_at" not in item:
        item["lastAccessedAt"] = item.get("createdAt")
    return MemoryItem.model_validate(item)


def _apply_query(items: List[MemoryItem], query: MemoryQuery) -> List[MemoryItem]:
    now_ms = query.now or int(datetime.now(timezone.utc).timestamp() * 1000)
    scored: List[tuple[MemoryItem, float]] = []

    for item in items:
        # 1. Expiry Check
        if not query.include_expired:
            if item.ttl_seconds:
                try:
                    c_ms = int(datetime.fromisoformat(item.created_at).timestamp() * 1000)
                    if c_ms + item.ttl_seconds * 1000 <= now_ms:
                        continue
                except (ValueError, TypeError, OSError) as exc:
                    logger.warning(
                        "Bad created_at for item %s, treating as non-expired: %s", item.id, exc
                    )

        # 2. Salience Calculation (with time decay)
        salience = item.salience or 1.0
        if query.half_life_seconds and query.half_life_seconds > 0:
            try:
                c_ms = int(datetime.fromisoformat(item.created_at).timestamp() * 1000)
                age_s = (now_ms - c_ms) / 1000
                decay = 0.5 ** (age_s / query.half_life_seconds)
                salience *= decay
            except (ValueError, TypeError, OSError) as exc:
                logger.warning("Bad created_at for item %s, skipping decay: %s", item.id, exc)

        # 3. Vector Similarity (Semantic Relevance)
        relevance = 0.0
        if query.vector and item.embedding:
            try:
                relevance = _cosine_similarity(query.vector, item.embedding)
            except ValueError:
                relevance = 0.0
        elif query.vector:
            # If query has vector but item doesn't, it's effectively 0 relevance
            relevance = 0.0
        else:
            # If no semantic query, relevance is 1.0 so alpha doesn't tank the score
            relevance = 1.0

        # 4. Hybrid Ranking (Combines relevance and salience)
        # score = alpha * relevance + (1 - alpha) * salience
        hybrid_score = (query.alpha * relevance) + ((1.0 - query.alpha) * salience)

        # 5. Text Filter
        if query.text and query.text.lower() not in item.content.lower():
            continue

        if hybrid_score >= query.min_score:
            scored.append((item, hybrid_score))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    filtered = [item for item, _ in scored]

    if query.limit is not None:
        filtered = filtered[: query.limit]
    return filtered


class InMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._items: Dict[str, MemoryItem] = {}
        self._lock = threading.Lock()

    def put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        items = item if isinstance(item, list) else [item]
        normalized = [_normalize(entry) for entry in items]
        with self._lock:
            for entry in normalized:
                self._items[entry.id] = entry
        return normalized

    def get(self, item_id: str) -> Optional[MemoryItem]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            item.last_accessed_at = _now_iso()
            return item.model_copy()

    def query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        with self._lock:
            items = list(self._items.values())
        # Apply query is pure CPU, can run synchronously or in executor. It's fast enough.
        return _apply_query(items, query or MemoryQuery())

    def forget(self, item_id: str) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None

    async def consolidate(
        self, summarizer: Callable[[str], Awaitable[str]], salience_threshold: float = 0.3
    ) -> int:
        # Read cold items under the lock, copy out what we need
        with self._lock:
            cold_items = [
                (item_id, self._items[item_id].content)
                for item_id, i in self._items.items()
                if (i.salience or 1.0) < salience_threshold and not i.is_summary
            ]

        # Perform async summarizer work outside the lock
        results = []
        for item_id, content in cold_items:
            summary = await summarizer(content)
            results.append((item_id, summary))

        # Write results back under the lock
        with self._lock:
            for item_id, summary in results:
                if item_id in self._items:
                    item = self._items[item_id]
                    item.content = f"[Flashcard] {summary}"
                    item.is_summary = True
                    item.salience = salience_threshold + 0.1
                    item.updated_at = _now_iso()
        return len(cold_items)


class FileStore(MemoryStore):
    def __init__(
        self,
        file_path: str,
        lock_timeout: float = 5.0,
        stale_lock_age: float = 10.0,
        disable_locking: bool = False,
    ) -> None:
        self.file_path = file_path
        self._items: Dict[str, MemoryItem] = {}
        self._loaded = False
        self._last_mtime: Optional[float] = None
        self._lock = threading.Lock()
        self._lock_timeout = lock_timeout
        self._stale_lock_age = stale_lock_age
        self._disable_locking = disable_locking
        self._lock_path = self.file_path + ".lock"

    def _load(self):
        # Reload if disk changed since last load (cross-process safety): another
        # process holding the file lock may have committed writes we must not clobber.
        try:
            current_mtime: Optional[float] = os.path.getmtime(self.file_path)
        except FileNotFoundError:
            current_mtime = None
        if self._loaded and current_mtime == self._last_mtime:
            return
        dirname = os.path.dirname(self.file_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        # Reset before re-reading so entries deleted by other processes are not resurrected.
        self._items = {}
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                for lineno, line in enumerate(f, 1):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        i = MemoryItem.model_validate(json.loads(stripped))
                        self._items[i.id] = i
                    except Exception as exc:
                        logger.warning(
                            "Skipping corrupted line %d in %s: %s", lineno, self.file_path, exc
                        )
        self._loaded = True
        self._last_mtime = current_mtime

    def _persist(self):
        # Atomic write: write to temp file, then rename (atomic on POSIX).
        tmp_path = self.file_path + ".tmp"
        with open(tmp_path, "w") as f:
            for i in self._items.values():
                f.write(i.model_dump_json(by_alias=True) + "\n")
        os.replace(tmp_path, self.file_path)
        # Record our own write's mtime so it does not trigger a needless reload.
        try:
            self._last_mtime = os.path.getmtime(self.file_path)
        except FileNotFoundError:
            self._last_mtime = None

    @contextmanager
    def _with_file_lock(self) -> Generator[None, None, None]:
        """Advisory file lock using exclusive file creation.

        Uses os.open with O_CREAT | O_EXCL for atomic lock acquisition.
        Writes PID + timestamp for debugging. Retries with exponential
        backoff and detects stale locks via mtime.
        """
        if self._disable_locking:
            yield
            return

        backoff = 0.05  # 50ms base
        deadline = time.monotonic() + self._lock_timeout

        while True:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, f"pid={os.getpid()} ts={time.time()}\n".encode())
                finally:
                    os.close(fd)
                break
            except FileExistsError:
                # Check for stale lock
                try:
                    mtime = os.path.getmtime(self._lock_path)
                    if time.time() - mtime > self._stale_lock_age:
                        logger.warning(
                            "Removing stale lock file %s (age=%.1fs)",
                            self._lock_path,
                            time.time() - mtime,
                        )
                        try:
                            os.unlink(self._lock_path)
                        except FileNotFoundError:
                            pass  # Another process beat us to it
                        continue
                except FileNotFoundError:
                    # Lock was released between our open attempt and stat
                    continue

                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire file lock {self._lock_path} "
                        f"within {self._lock_timeout}s"
                    )

                time.sleep(backoff)
                backoff = min(backoff * 2, 1.0)

        try:
            yield
        finally:
            try:
                os.unlink(self._lock_path)
            except FileNotFoundError:
                pass

    def _sync_put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        with self._with_file_lock():
            with self._lock:
                self._load()
                items = item if isinstance(item, list) else [item]
                normalized = [_normalize(entry) for entry in items]
                for entry in normalized:
                    self._items[entry.id] = entry
                self._persist()
                return normalized

    def put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        return self._sync_put(item)

    def _sync_get(self, item_id: str) -> Optional[MemoryItem]:
        with self._with_file_lock():
            with self._lock:
                self._load()
                item = self._items.get(item_id)
                if item:
                    item.last_accessed_at = _now_iso()
                    self._persist()
                    return item.model_copy()
                return None

    def get(self, item_id: str) -> Optional[MemoryItem]:
        return self._sync_get(item_id)

    def _sync_query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        with self._lock:
            self._load()
            items = list(self._items.values())
        return _apply_query(items, query or MemoryQuery())

    def query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        return self._sync_query(query)

    def _sync_forget(self, item_id: str) -> bool:
        with self._with_file_lock():
            with self._lock:
                self._load()
                removed = self._items.pop(item_id, None) is not None
                if removed:
                    self._persist()
                return removed

    def forget(self, item_id: str) -> bool:
        return self._sync_forget(item_id)

    async def consolidate(self, summarizer, salience_threshold=0.3):
        # Read cold items under the lock, copy out what we need
        with self._lock:
            self._load()
            cold_items = [
                (item_id, item.content)
                for item_id, item in self._items.items()
                if (item.salience or 1.0) < salience_threshold and not item.is_summary
            ]

        # Perform async summarizer work outside the lock
        results = []
        for item_id, content in cold_items:
            summary = await summarizer(content)
            results.append((item_id, summary))

        # Write results back under the lock
        with self._lock:
            for item_id, summary in results:
                if item_id in self._items:
                    item = self._items[item_id]
                    item.content = f"[Flashcard] {summary}"
                    item.is_summary = True
                    item.salience = salience_threshold + 0.1
                    item.updated_at = _now_iso()
            if results:
                self._persist()
        return len(cold_items)


class SqliteStore(MemoryStore):
    def __init__(self, database_path: str) -> None:
        self.conn = sqlite3.connect(database_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._init()

    def _init(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT, last_accessed_at TEXT, salience REAL, ttl_seconds INTEGER,
                is_summary INTEGER DEFAULT 0, embedding_json TEXT, metadata_json TEXT
            )
        """)
        self.conn.commit()

    def _sync_put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        with self._lock:
            items = item if isinstance(item, list) else [item]
            normalized = [_normalize(e) for e in items]
            with self.conn:
                for e in normalized:
                    self.conn.execute(
                        """
                        INSERT INTO memory_items (id, content, created_at, updated_at, last_accessed_at, salience, ttl_seconds, is_summary, embedding_json, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at,
                        last_accessed_at=excluded.last_accessed_at, salience=excluded.salience, ttl_seconds=excluded.ttl_seconds,
                        is_summary=excluded.is_summary, embedding_json=excluded.embedding_json, metadata_json=excluded.metadata_json
                    """,
                        (
                            e.id,
                            e.content,
                            e.created_at,
                            e.updated_at or e.created_at,
                            e.last_accessed_at or e.created_at,
                            e.salience,
                            e.ttl_seconds,
                            1 if e.is_summary else 0,
                            json.dumps(e.embedding) if e.embedding else None,
                            json.dumps(e.metadata or {}),
                        ),
                    )
            return normalized

    def put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        return self._sync_put(item)

    def _sync_get(self, item_id: str):
        with self._lock:
            self.conn.execute(
                "UPDATE memory_items SET last_accessed_at = ? WHERE id = ?", (_now_iso(), item_id)
            )
            self.conn.commit()
            r = self.conn.execute(
                "SELECT id, content, created_at, updated_at, last_accessed_at, salience, ttl_seconds, is_summary, embedding_json, metadata_json FROM memory_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if not r:
                return None
            return MemoryItem(
                id=r[0],
                content=r[1],
                createdAt=r[2],
                updatedAt=r[3],
                lastAccessedAt=r[4],
                salience=r[5],
                ttlSeconds=r[6],
                isSummary=bool(r[7]),
                embedding=json.loads(r[8]) if r[8] else None,
                metadata=json.loads(r[9]) if r[9] else {},
            )

    def get(self, item_id: str) -> Optional[MemoryItem]:
        return self._sync_get(item_id)

    def _sync_query(self, query: Optional[MemoryQuery] = None):
        with self._lock:
            cursor = self.conn.execute(
                "SELECT id, content, created_at, updated_at, last_accessed_at, salience, ttl_seconds, is_summary, embedding_json, metadata_json FROM memory_items"
            )
            items = [
                MemoryItem(
                    id=r[0],
                    content=r[1],
                    createdAt=r[2],
                    updatedAt=r[3],
                    lastAccessedAt=r[4],
                    salience=r[5],
                    ttlSeconds=r[6],
                    isSummary=bool(r[7]),
                    embedding=json.loads(r[8]) if r[8] else None,
                    metadata=json.loads(r[9]) if r[9] else {},
                )
                for r in cursor.fetchall()
            ]
        return _apply_query(items, query or MemoryQuery())

    def query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        return self._sync_query(query)

    def _sync_forget(self, item_id: str):
        with self._lock:
            c = self.conn.execute("DELETE FROM memory_items WHERE id = ?", (item_id,))
            self.conn.commit()
            return c.rowcount > 0

    def forget(self, item_id: str) -> bool:
        return bool(self._sync_forget(item_id))

    def close(self):
        with self._lock:
            self.conn.close()

    async def consolidate(self, summarizer, salience_threshold=0.3):
        # Read cold items under the lock, then release before async work
        with self._lock:
            cold = self.conn.execute(
                "SELECT id, content FROM memory_items WHERE salience < ? AND is_summary = 0",
                (salience_threshold,),
            ).fetchall()

        # Perform async summarizer work outside the lock
        results = []
        for i_id, content in cold:
            s = await summarizer(content)
            results.append((i_id, s))

        # Write results back under the lock
        with self._lock:
            for i_id, s in results:
                with self.conn:
                    self.conn.execute(
                        "UPDATE memory_items SET content = ?, is_summary = 1, salience = ?, updated_at = ? WHERE id = ?",
                        (f"[Flashcard] {s}", salience_threshold + 0.1, _now_iso(), i_id),
                    )
        return len(cold)
