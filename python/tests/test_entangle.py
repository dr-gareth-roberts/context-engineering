"""Tests for the context entanglement mesh."""

from __future__ import annotations

import pytest

from context_engineering.core import Budget, ContextItem
from context_engineering.entangle import (
    EntangledItem,
    EntangleOptions,
    MeshConfig,
    create_entanglement_mesh,
    filter_for_agent,
    is_expired,
    matches_kind_filter,
    matches_scope,
)


def _item(id: str, content: str | None = None, kind: str | None = None) -> ContextItem:
    return ContextItem(
        id=id,
        content=content or f"content for {id}",
        kind=kind,
        priority=5,
        tokens=10,
    )


def _budget(max_tokens: int = 1000) -> Budget:
    return Budget(max_tokens=max_tokens)


def _entangled(
    id: str = "item-1",
    source: str = "agent-a",
    propagation: str = "next-pack",
    scope: list[str] | str = "*",
    kind: str | None = None,
    expires_at: float | None = None,
) -> EntangledItem:
    return EntangledItem(
        item=ContextItem(id=id, content="test", kind=kind, priority=5),
        source_agent=source,
        propagation=propagation,
        scope=scope,
        entangled_at=1000.0,
        expires_at=expires_at,
    )


class TestPropagationHelpers:
    def test_is_expired_false_when_no_expiry(self):
        ei = _entangled()
        assert is_expired(ei) is False

    def test_is_expired_true_when_past_expiry(self):
        ei = _entangled(expires_at=500.0)
        assert is_expired(ei, now=600.0) is True

    def test_matches_scope_wildcard(self):
        ei = _entangled(scope="*")
        assert matches_scope(ei, "agent-b") is True

    def test_matches_scope_excludes_self(self):
        ei = _entangled(scope="*", source="agent-a")
        assert matches_scope(ei, "agent-a") is False

    def test_matches_scope_specific(self):
        ei = _entangled(scope=["agent-b"])
        assert matches_scope(ei, "agent-b") is True
        assert matches_scope(ei, "agent-c") is False

    def test_matches_kind_filter_no_filter(self):
        ei = _entangled()
        assert matches_kind_filter(ei) is True

    def test_matches_kind_filter_matching(self):
        ei = _entangled(kind="code")
        assert matches_kind_filter(ei, ["code", "doc"]) is True

    def test_matches_kind_filter_no_match(self):
        ei = _entangled(kind="code")
        assert matches_kind_filter(ei, ["doc"]) is False

    def test_filter_for_agent_excludes_expired(self):
        items = [
            _entangled(id="old", expires_at=100.0),
            _entangled(id="alive"),
        ]
        result = filter_for_agent(items, "agent-b", now=200.0)
        assert len(result) == 1
        assert result[0].item.id == "alive"

    def test_filter_for_agent_excludes_on_demand_for_pack(self):
        items = [_entangled(propagation="on-demand")]
        result = filter_for_agent(items, "agent-b", for_pack=True)
        assert len(result) == 0

    def test_filter_for_agent_includes_on_demand_normally(self):
        items = [_entangled(propagation="on-demand")]
        result = filter_for_agent(items, "agent-b", for_pack=False)
        assert len(result) == 1


class TestEntanglementMesh:
    def test_register_and_get_agent(self):
        mesh = create_entanglement_mesh()
        handle = mesh.register("agent-a", budget=_budget())
        assert handle.agent_id == "agent-a"
        assert mesh.get_agent("agent-a") is not None

    def test_register_duplicate_raises(self):
        mesh = create_entanglement_mesh()
        mesh.register("agent-a", budget=_budget())
        with pytest.raises(ValueError, match="already registered"):
            mesh.register("agent-a", budget=_budget())

    def test_entangle_and_get_pending(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        mesh.register("agent-b", budget=_budget())

        handle_a.entangle(_item("shared"))

        handle_b = mesh.get_agent("agent-b")
        assert handle_b is not None
        pending = handle_b.get_pending()
        assert len(pending) == 1
        assert pending[0].item.id == "shared"

    def test_agent_cannot_see_own_items(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())

        handle_a.entangle(_item("self"))
        assert len(handle_a.get_pending()) == 0

    def test_scope_filtering(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        mesh.register("agent-b", budget=_budget())
        mesh.register("agent-c", budget=_budget())

        handle_a.entangle(_item("scoped"), EntangleOptions(scope=["agent-b"]))

        assert len(mesh.get_agent("agent-b").get_pending()) == 1
        assert len(mesh.get_agent("agent-c").get_pending()) == 0

    def test_kind_filtering(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        mesh.register("agent-b", budget=_budget(), kind_filter=["code"])

        handle_a.entangle(_item("code-item", kind="code"))
        handle_a.entangle(_item("doc-item", kind="doc"))

        handle_b = mesh.get_agent("agent-b")
        pending = handle_b.get_pending()
        assert len(pending) == 1
        assert pending[0].item.id == "code-item"

    def test_acknowledge_removes_immediate_items(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        handle_b = mesh.register("agent-b", budget=_budget())

        handle_a.entangle(_item("ack-me"), EntangleOptions(propagation="immediate"))

        assert len(handle_b.get_pending()) == 1
        handle_b.acknowledge("ack-me")
        assert len(handle_b.get_pending()) == 0

    def test_pack_includes_entangled_items(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        handle_b = mesh.register("agent-b", budget=_budget())

        handle_a.entangle(_item("from-a"))

        result = handle_b.pack([_item("own")])
        selected_ids = [s.id for s in result.selected]
        assert "from-a" in selected_ids
        assert "own" in selected_ids

    def test_on_demand_not_in_pack(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        handle_b = mesh.register("agent-b", budget=_budget())

        handle_a.entangle(_item("od"), EntangleOptions(propagation="on-demand"))

        result = handle_b.pack([_item("own")])
        selected_ids = [s.id for s in result.selected]
        assert "od" not in selected_ids

    def test_stats(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        mesh.register("agent-b", budget=_budget())

        handle_a.entangle(_item("i1"))
        handle_a.entangle(_item("i2"), EntangleOptions(scope=["agent-b"]))

        s = mesh.stats()
        assert s.total_items == 2
        assert s.active_agents == 2
        assert s.items_by_source["agent-a"] == 2

    def test_clear(self):
        mesh = create_entanglement_mesh()
        handle = mesh.register("agent-a", budget=_budget())
        handle.entangle(_item("gone"))

        mesh.clear()
        assert mesh.stats().total_items == 0
        assert len(mesh.list_agents()) == 1

    def test_export_import_round_trip(self):
        mesh = create_entanglement_mesh()
        handle_a = mesh.register("agent-a", budget=_budget())
        mesh.register("agent-b", budget=_budget())

        handle_a.entangle(_item("shared"))

        exported = mesh.export_state()

        mesh2 = create_entanglement_mesh()
        mesh2.import_state(exported)

        assert mesh2.stats().total_items == 1
        assert len(mesh2.list_agents()) == 2

    def test_max_items_pruning(self):
        mesh = create_entanglement_mesh(MeshConfig(max_items=3))
        handle = mesh.register("agent-a", budget=_budget())

        for i in range(5):
            handle.entangle(_item(f"item-{i}"))

        assert mesh.stats().total_items == 3

    def test_unregister(self):
        mesh = create_entanglement_mesh()
        handle = mesh.register("agent-a", budget=_budget())

        handle.unregister()
        assert mesh.get_agent("agent-a") is None
        assert len(mesh.list_agents()) == 0

    def test_on_entangle_callback(self):
        calls: list[EntangledItem] = []
        mesh = create_entanglement_mesh(MeshConfig(on_entangle=lambda ei: calls.append(ei)))
        handle = mesh.register("agent-a", budget=_budget())

        handle.entangle(_item("cb"))
        assert len(calls) == 1
        assert calls[0].item.id == "cb"
