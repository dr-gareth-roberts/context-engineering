from typing import List, Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from .memory import MemoryItem, MemoryQuery, MemoryStore, _apply_query, _normalize, _now_iso


class RedisMemoryStore(MemoryStore):
    def __init__(self, url: str):
        if redis is None:
            raise ImportError(
                "redis package is required for RedisMemoryStore. Install it with `pip install redis`."
            )
        self.client = redis.from_url(url)

    async def aput(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        items = item if isinstance(item, list) else [item]
        normalized = [_normalize(e) for e in items]

        async with self.client.pipeline() as pipe:
            for entry in normalized:
                data = entry.model_dump_json(by_alias=True)
                key = f"ce_memory:{entry.id}"
                if entry.ttl_seconds and entry.ttl_seconds > 0:
                    pipe.set(key, data, ex=entry.ttl_seconds)
                else:
                    pipe.set(key, data)
            await pipe.execute()
        return normalized

    async def aget(self, item_id: str) -> Optional[MemoryItem]:
        data = await self.client.get(f"ce_memory:{item_id}")
        if not data:
            return None

        item = MemoryItem.model_validate_json(data)
        item.last_accessed_at = _now_iso()

        # update last_accessed_at in redis; keepttl preserves the key's existing
        # native expiry so reads do not slide the absolute TTL (created_at + ttl).
        key = f"ce_memory:{item_id}"
        dumped = item.model_dump_json(by_alias=True)
        await self.client.set(key, dumped, keepttl=True)

        return item

    async def aquery(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        # Use SCAN instead of KEYS to avoid blocking the Redis server.
        # In a real production scenario, use RediSearch for better performance.
        keys: list = []
        cursor = 0
        while True:
            cursor, batch = await self.client.scan(cursor, match="ce_memory:*", count=100)
            keys.extend(batch)
            if cursor == 0:
                break

        if not keys:
            return []

        values = await self.client.mget(keys)
        items = []
        for val in values:
            if val:
                items.append(MemoryItem.model_validate_json(val))

        return _apply_query(items, query or MemoryQuery())

    async def aforget(self, item_id: str) -> bool:
        res = await self.client.delete(f"ce_memory:{item_id}")
        return res > 0

    def put(self, item: MemoryItem | List[MemoryItem]) -> List[MemoryItem]:
        raise NotImplementedError("RedisMemoryStore is async-only. Use aput().")

    def get(self, item_id: str) -> Optional[MemoryItem]:
        raise NotImplementedError("RedisMemoryStore is async-only. Use aget().")

    def query(self, query: Optional[MemoryQuery] = None) -> List[MemoryItem]:
        raise NotImplementedError("RedisMemoryStore is async-only. Use aquery().")

    def forget(self, item_id: str) -> bool:
        raise NotImplementedError("RedisMemoryStore is async-only. Use aforget().")
