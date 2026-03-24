"""
Context Entanglement - a pub/sub mesh for multi-agent context sharing.

When Agent A discovers something important, it "entangles" that item so
Agent B's next pack() automatically includes it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .core import Budget, ContextItem, ContextPack, pack

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

PropagationPolicy = Literal["immediate", "next-pack", "on-demand"]


@dataclass
class EntangledItem:
    item: ContextItem
    source_agent: str
    propagation: PropagationPolicy
    scope: list[str] | Literal["*"]
    entangled_at: float
    expires_at: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class AgentRegistration:
    agent_id: str
    budget: Budget
    kind_filter: list[str] | None = None


@dataclass
class EntangleOptions:
    propagation: PropagationPolicy | None = None
    scope: list[str] | Literal["*"] | None = None
    expires_in: float | None = None
    priority: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class MeshConfig:
    default_propagation: PropagationPolicy = "next-pack"
    default_ttl: float | None = None
    max_items: int = 1000
    on_entangle: Callable[[EntangledItem], None] | None = None
    on_inject: Callable[[EntangledItem, str], None] | None = None


@dataclass
class MeshState:
    items: list[EntangledItem]
    agents: list[AgentRegistration]


@dataclass
class MeshStats:
    total_items: int
    active_agents: int
    items_by_source: dict[str, int]
    items_by_scope: dict[str, int]


# ---------------------------------------------------------------------------
# Propagation helpers
# ---------------------------------------------------------------------------


def is_expired(item: EntangledItem, now: float | None = None) -> bool:
    if item.expires_at is None:
        return False
    return (now or time.time() * 1000) >= item.expires_at


def matches_scope(item: EntangledItem, agent_id: str) -> bool:
    if item.source_agent == agent_id:
        return False
    if item.scope == "*":
        return True
    return agent_id in item.scope


def matches_kind_filter(item: EntangledItem, kind_filter: list[str] | None = None) -> bool:
    if not kind_filter:
        return True
    item_kind = item.item.kind
    if not item_kind:
        return False
    return item_kind in kind_filter


def filter_for_agent(
    items: list[EntangledItem],
    agent_id: str,
    kind_filter: list[str] | None = None,
    *,
    acknowledged: set[str] | None = None,
    for_pack: bool = False,
    now: float | None = None,
) -> list[EntangledItem]:
    """Filter entangled items visible to a specific agent."""
    effective_now = now or time.time() * 1000
    ack = acknowledged or set()
    result: list[EntangledItem] = []

    for ei in items:
        if is_expired(ei, effective_now):
            continue
        if not matches_scope(ei, agent_id):
            continue
        if not matches_kind_filter(ei, kind_filter):
            continue
        if for_pack and ei.propagation == "on-demand":
            continue
        if ei.propagation == "immediate" and ei.item.id in ack:
            continue
        result.append(ei)

    return result


# ---------------------------------------------------------------------------
# Agent Handle
# ---------------------------------------------------------------------------


class AgentHandle:
    """Per-agent handle for interacting with the entanglement mesh."""

    def __init__(
        self,
        registration: AgentRegistration,
        store: _MeshStore,
    ) -> None:
        self._registration = registration
        self._store = store
        self._acknowledged: set[str] = set()

    @property
    def agent_id(self) -> str:
        return self._registration.agent_id

    def entangle(self, item: ContextItem, options: EntangleOptions | None = None) -> None:
        """Publish an item to other agents via the mesh."""
        opts = options or EntangleOptions()
        propagation = opts.propagation or self._store.config.default_propagation
        now = time.time() * 1000

        context_item = item
        if opts.priority is not None:
            context_item = ContextItem(
                id=item.id,
                content=item.content,
                kind=item.kind,
                priority=opts.priority,
                recency=item.recency,
                tokens=item.tokens,
                score=item.score,
                metadata=item.metadata,
                compressions=item.compressions,
                supersedes=item.supersedes,
                embedding=item.embedding,
                parent_id=item.parent_id,
                cost=item.cost,
                latency=item.latency,
                links=item.links,
            )

        expires_at: float | None = None
        if opts.expires_in is not None:
            expires_at = now + opts.expires_in
        elif self._store.config.default_ttl is not None:
            expires_at = now + self._store.config.default_ttl

        entangled = EntangledItem(
            item=context_item,
            source_agent=self.agent_id,
            propagation=propagation,
            scope=opts.scope if opts.scope is not None else "*",
            entangled_at=now,
            expires_at=expires_at,
            metadata=opts.metadata,
        )

        self._store.items.append(entangled)

        # Prune oldest if over max
        max_items = self._store.config.max_items
        if len(self._store.items) > max_items:
            excess = len(self._store.items) - max_items
            del self._store.items[:excess]

        if self._store.config.on_entangle:
            self._store.config.on_entangle(entangled)

    def pack(
        self,
        items: list[ContextItem],
        budget: Budget | None = None,
        **pack_kwargs: Any,
    ) -> ContextPack:
        """Pack this agent's items with entangled items from the mesh injected.

        Returns a ContextPack. The ``stats`` dict contains extra keys:
        ``entangled_items`` and ``own_items``.
        """
        reg = self._store.agents.get(self.agent_id)
        effective_budget = budget or (reg.budget if reg else Budget(max_tokens=4096))
        kind_filter = reg.kind_filter if reg else None

        pending = filter_for_agent(
            self._store.items,
            self.agent_id,
            kind_filter,
            acknowledged=self._acknowledged,
            for_pack=True,
        )

        entangled_context_items = [ei.item for ei in pending]
        all_items = list(items) + entangled_context_items

        result = pack(all_items, effective_budget, **pack_kwargs)

        selected_ids = {s.id for s in result.selected}

        if self._store.config.on_inject:
            for ei in pending:
                if ei.item.id in selected_ids:
                    self._store.config.on_inject(ei, self.agent_id)

        injected = [ei for ei in pending if ei.item.id in selected_ids]
        own_selected = [i for i in items if i.id in selected_ids]

        result.stats["entangled_items"] = injected
        result.stats["own_items"] = own_selected

        return result

    def get_pending(self) -> list[EntangledItem]:
        """Get pending entangled items for this agent without packing."""
        reg = self._store.agents.get(self.agent_id)
        kind_filter = reg.kind_filter if reg else None
        return filter_for_agent(
            self._store.items,
            self.agent_id,
            kind_filter,
            acknowledged=self._acknowledged,
            for_pack=False,
        )

    def acknowledge(self, *item_ids: str) -> None:
        """Acknowledge items. Removes immediate items from pending."""
        for item_id in item_ids:
            self._acknowledged.add(item_id)

    def unregister(self) -> None:
        """Unregister from the mesh."""
        self._store.agents.pop(self.agent_id, None)
        self._store.handles.pop(self.agent_id, None)


# ---------------------------------------------------------------------------
# Internal store
# ---------------------------------------------------------------------------


@dataclass
class _MeshStore:
    items: list[EntangledItem] = field(default_factory=list)
    agents: dict[str, AgentRegistration] = field(default_factory=dict)
    handles: dict[str, AgentHandle] = field(default_factory=dict)
    config: MeshConfig = field(default_factory=MeshConfig)


# ---------------------------------------------------------------------------
# Entanglement Mesh
# ---------------------------------------------------------------------------


class EntanglementMesh:
    """A shared fabric connecting multiple agents for context sharing."""

    def __init__(self, config: MeshConfig | None = None) -> None:
        self._store = _MeshStore(config=config or MeshConfig())

    def register(
        self,
        agent_id: str,
        budget: Budget | None = None,
        kind_filter: list[str] | None = None,
    ) -> AgentHandle:
        """Register an agent and get a handle."""
        if agent_id in self._store.agents:
            raise ValueError(f'Agent "{agent_id}" is already registered in the mesh')

        registration = AgentRegistration(
            agent_id=agent_id,
            budget=budget or Budget(max_tokens=4096),
            kind_filter=kind_filter,
        )
        self._store.agents[agent_id] = registration

        handle = AgentHandle(registration, self._store)
        self._store.handles[agent_id] = handle

        return handle

    def get_agent(self, agent_id: str) -> AgentHandle | None:
        """Get an existing agent handle."""
        return self._store.handles.get(agent_id)

    def list_agents(self) -> list[AgentRegistration]:
        """List all registered agents."""
        return list(self._store.agents.values())

    def stats(self) -> MeshStats:
        """Get mesh statistics."""
        items_by_source: dict[str, int] = {}
        items_by_scope: dict[str, int] = {}

        for ei in self._store.items:
            items_by_source[ei.source_agent] = items_by_source.get(ei.source_agent, 0) + 1
            if ei.scope == "*":
                items_by_scope["*"] = items_by_scope.get("*", 0) + 1
            else:
                for target in ei.scope:
                    items_by_scope[target] = items_by_scope.get(target, 0) + 1

        return MeshStats(
            total_items=len(self._store.items),
            active_agents=len(self._store.agents),
            items_by_source=items_by_source,
            items_by_scope=items_by_scope,
        )

    def clear(self) -> None:
        """Clear all entangled items."""
        self._store.items.clear()

    def export_state(self) -> MeshState:
        """Export state for persistence."""
        return MeshState(
            items=list(self._store.items),
            agents=list(self._store.agents.values()),
        )

    def import_state(self, state: MeshState) -> None:
        """Import previously exported state."""
        self._store.items.clear()
        self._store.items.extend(state.items)

        for reg in state.agents:
            if reg.agent_id not in self._store.agents:
                self._store.agents[reg.agent_id] = reg
                handle = AgentHandle(reg, self._store)
                self._store.handles[reg.agent_id] = handle


def create_entanglement_mesh(
    config: MeshConfig | None = None,
) -> EntanglementMesh:
    """Create an entanglement mesh for multi-agent context sharing."""
    return EntanglementMesh(config)
