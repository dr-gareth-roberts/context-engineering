"""Tests for BEADS JSONL format support."""

import json
from datetime import datetime, timedelta, timezone

from context_engineering.beads import (
    BeadsBridgeOptions,
    BeadsDependency,
    BeadsIssue,
    HandoffOptions,
    beads_to_context_item,
    context_item_to_beads,
    create_handoff,
    get_ready_issues,
    merge_beads_jsonl,
    pickup_handoff,
    read_beads_jsonl,
    write_beads_jsonl,
)
from context_engineering.core import Budget, ContextItem, ContextPack


def make_item(id: str, kind: str, priority: float, tokens: int) -> ContextItem:
    return ContextItem(id=id, content=f"content-{id}", kind=kind, priority=priority, tokens=tokens)


def make_pack(items, dropped=None) -> ContextPack:
    dropped = dropped or []
    return ContextPack(
        budget=Budget(max_tokens=500),
        selected=items,
        dropped=dropped,
        total_tokens=sum(i.tokens or 0 for i in items),
    )


def make_issue(**kwargs) -> BeadsIssue:
    defaults = {
        "id": "bd-1",
        "title": "Test",
        "status": "open",
        "priority": 2,
        "issue_type": "task",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    defaults.update(kwargs)
    return BeadsIssue(**defaults)


# ─── readBeadsJSONL / writeBeadsJSONL ─────────────────────────────────


class TestReadBeadsJSONL:
    def test_parses_valid_jsonl(self):
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "id": "bd-1",
                        "title": "A",
                        "status": "open",
                        "priority": 2,
                        "issue_type": "task",
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                    }
                ),
                json.dumps(
                    {
                        "id": "bd-2",
                        "title": "B",
                        "status": "closed",
                        "priority": 1,
                        "issue_type": "bug",
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                    }
                ),
            ]
        )
        issues = read_beads_jsonl(jsonl)
        assert len(issues) == 2
        assert issues[0].id == "bd-1"
        assert issues[1].id == "bd-2"

    def test_skips_blank_lines_and_comments(self):
        jsonl = "\n".join(
            [
                "# Comment",
                "",
                json.dumps(
                    {
                        "id": "bd-1",
                        "title": "A",
                        "status": "open",
                        "priority": 2,
                        "issue_type": "task",
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                    }
                ),
                "",
                "# Another comment",
            ]
        )
        issues = read_beads_jsonl(jsonl)
        assert len(issues) == 1

    def test_skips_malformed_lines(self):
        jsonl = "\n".join(
            [
                "not json",
                json.dumps(
                    {
                        "id": "bd-1",
                        "title": "A",
                        "status": "open",
                        "priority": 2,
                        "issue_type": "task",
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                    }
                ),
                "{bad",
            ]
        )
        issues = read_beads_jsonl(jsonl)
        assert len(issues) == 1

    def test_skips_objects_without_id(self):
        jsonl = "\n".join(
            [
                json.dumps({"title": "No ID"}),
                json.dumps(
                    {
                        "id": "bd-1",
                        "title": "Has ID",
                        "status": "open",
                        "priority": 2,
                        "issue_type": "task",
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                    }
                ),
            ]
        )
        issues = read_beads_jsonl(jsonl)
        assert len(issues) == 1

    def test_handles_empty_input(self):
        assert len(read_beads_jsonl("")) == 0
        assert len(read_beads_jsonl("\n\n")) == 0


class TestWriteBeadsJSONL:
    def test_serializes_issues(self):
        issues = [make_issue(id="bd-1", title="A"), make_issue(id="bd-2", title="B")]
        jsonl = write_beads_jsonl(issues)
        lines = jsonl.split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["id"] == "bd-1"

    def test_roundtrips(self):
        issues = [make_issue(id="bd-1", labels=["test"])]
        jsonl = write_beads_jsonl(issues)
        parsed = read_beads_jsonl(jsonl)
        assert len(parsed) == 1
        assert parsed[0].labels == ["test"]


# ─── ContextItem ↔ BeadsIssue Bridge ─────────────────────────────────


class TestContextItemToBeads:
    def test_converts_item(self):
        item = make_item("sys-prompt", "system", 10, 100)
        issue = context_item_to_beads(item)

        assert issue.id == "ce-sys-prompt"
        assert issue.title == "sys-prompt"
        assert issue.description == "content-sys-prompt"
        assert issue.issue_type == "context"
        assert issue.source_system == "context-engineering"
        assert "kind:system" in issue.labels
        assert "context-engineering" in issue.labels

    def test_maps_priority(self):
        high = context_item_to_beads(make_item("a", "system", 10, 50))
        low = context_item_to_beads(make_item("b", "system", 1, 50))
        assert high.priority < low.priority

    def test_stores_ce_metadata(self):
        item = ContextItem(
            id="test",
            content="hello",
            kind="memory",
            priority=7,
            recency=0.8,
            tokens=50,
            score=6.5,
        )
        issue = context_item_to_beads(item)
        ce = issue.metadata["_ce"]

        assert ce["kind"] == "memory"
        assert ce["priority"] == 7
        assert ce["recency"] == 0.8
        assert ce["tokens"] == 50
        assert ce["originalId"] == "test"

    def test_respects_bridge_options(self):
        item = make_item("a", "system", 5, 50)
        issue = context_item_to_beads(
            item,
            BeadsBridgeOptions(
                agent="agent-007",
                source_system="my-app",
                default_status="pinned",
            ),
        )

        assert issue.assignee == "agent-007"
        assert issue.source_system == "my-app"
        assert issue.status == "pinned"


class TestBeadsToContextItem:
    def test_recovers_original(self):
        original = make_item("sys-prompt", "system", 10, 100)
        issue = context_item_to_beads(original)
        recovered = beads_to_context_item(issue)

        assert recovered.id == "sys-prompt"
        assert recovered.content == "content-sys-prompt"
        assert recovered.kind == "system"
        assert recovered.priority == 10
        assert recovered.tokens == 100

    def test_infers_kind_from_labels(self):
        issue = make_issue(
            id="bd-test",
            description="content",
            issue_type="context",
            labels=["kind:retrieval"],
        )
        item = beads_to_context_item(issue)
        assert item.kind == "retrieval"

    def test_infers_priority_from_beads(self):
        issue = make_issue(id="bd-test", description="content", priority=0)
        item = beads_to_context_item(issue)
        assert item.priority == 10

    def test_roundtrips(self):
        original = ContextItem(
            id="my-item",
            content="important context",
            kind="memory",
            priority=7,
            recency=0.9,
            tokens=42,
        )
        issue = context_item_to_beads(original)
        recovered = beads_to_context_item(issue)

        assert recovered.id == original.id
        assert recovered.content == original.content
        assert recovered.kind == original.kind
        assert recovered.priority == original.priority
        assert recovered.recency == original.recency
        assert recovered.tokens == original.tokens


# ─── Agent Handoff / Pickup ───────────────────────────────────────────


class TestCreateHandoff:
    def test_creates_jsonl(self):
        pack = make_pack(
            [
                make_item("sys", "system", 10, 100),
                make_item("doc", "retrieval", 7, 50),
            ]
        )
        result = create_handoff(pack)

        assert len(result.issues) == 3  # manifest + 2 items
        assert result.stats["activeItems"] == 2
        assert result.stats["deferredItems"] == 0
        assert result.jsonl

    def test_includes_dropped(self):
        pack = make_pack(
            [make_item("sys", "system", 10, 100)],
            [make_item("low", "memory", 2, 50)],
        )
        result = create_handoff(pack, HandoffOptions(include_dropped=True))

        assert result.stats["activeItems"] == 1
        assert result.stats["deferredItems"] == 1
        assert len(result.issues) == 3

    def test_includes_manifest_metadata(self):
        pack = make_pack([make_item("a", "system", 10, 100)])
        result = create_handoff(
            pack,
            HandoffOptions(
                agent="agent-1",
                session_id="session-xyz",
                handoff_notes="Completed phase 1",
            ),
        )

        manifest = result.issues[0]
        assert manifest.id.startswith("ce-handoff-")
        assert manifest.status == "pinned"
        assert manifest.description == "Completed phase 1"
        meta = manifest.metadata["_ce_handoff"]
        assert meta["sessionId"] == "session-xyz"
        assert meta["totalTokens"] == 100


class TestPickupHandoff:
    def test_recovers_items(self):
        pack = make_pack(
            [
                make_item("sys", "system", 10, 100),
                make_item("doc", "retrieval", 7, 50),
            ]
        )
        handoff = create_handoff(pack, HandoffOptions(agent="agent-1"))
        pickup = pickup_handoff(handoff.jsonl)

        assert len(pickup.items) == 2
        assert pickup.items[0].id == "sys"
        assert pickup.items[1].id == "doc"
        assert pickup.manifest is not None

    def test_separates_deferred(self):
        pack = make_pack(
            [make_item("active", "system", 10, 100)],
            [make_item("deferred", "memory", 2, 50)],
        )
        handoff = create_handoff(pack, HandoffOptions(include_dropped=True))
        pickup = pickup_handoff(handoff.jsonl)

        assert len(pickup.items) == 1
        assert pickup.items[0].id == "active"
        assert len(pickup.deferred) == 1
        assert pickup.deferred[0].id == "deferred"

    def test_separates_work_items(self):
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "id": "ce-handoff-test",
                        "title": "Handoff",
                        "status": "pinned",
                        "priority": 0,
                        "issue_type": "message",
                        "labels": ["handoff"],
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                        "metadata": {"_ce_handoff": {"sessionId": "s1"}},
                    }
                ),
                json.dumps(
                    {
                        "id": "ce-sys",
                        "title": "sys",
                        "description": "System prompt",
                        "status": "open",
                        "priority": 0,
                        "issue_type": "context",
                        "source_system": "context-engineering",
                        "labels": ["context-engineering", "kind:system"],
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                        "metadata": {
                            "_ce": {
                                "originalId": "sys",
                                "kind": "system",
                                "priority": 10,
                                "tokens": 50,
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "id": "bd-task-1",
                        "title": "Fix the bug",
                        "status": "open",
                        "priority": 1,
                        "issue_type": "bug",
                        "created_at": "2025-01-01",
                        "updated_at": "2025-01-01",
                    }
                ),
            ]
        )

        pickup = pickup_handoff(jsonl)
        assert len(pickup.items) == 1
        assert pickup.items[0].id == "sys"
        assert len(pickup.work_items) == 1
        assert pickup.work_items[0].id == "bd-task-1"
        assert pickup.stats["handoffSessionId"] == "s1"

    def test_full_roundtrip(self):
        original = [
            make_item("sys", "system", 10, 100),
            make_item("mem", "memory", 6, 80),
            make_item("query", "query", 8, 50),
        ]
        pack = make_pack(original)
        handoff = create_handoff(
            pack,
            HandoffOptions(
                agent="agent-1",
                session_id="roundtrip",
            ),
        )
        pickup = pickup_handoff(handoff.jsonl)

        assert len(pickup.items) == 3
        for orig in original:
            recovered = next(i for i in pickup.items if i.id == orig.id)
            assert recovered.content == orig.content
            assert recovered.kind == orig.kind
            assert recovered.priority == orig.priority
            assert recovered.tokens == orig.tokens

    def test_handles_empty(self):
        pickup = pickup_handoff("")
        assert len(pickup.items) == 0
        assert len(pickup.deferred) == 0
        assert pickup.manifest is None


# ─── Incremental Operations ──────────────────────────────────────────


class TestMergeBeadsJSONL:
    def test_merges_new_issues(self):
        existing = write_beads_jsonl([make_issue(id="bd-1", title="A")])
        updates = [make_issue(id="bd-2", title="B")]

        merged = merge_beads_jsonl(existing, updates)
        issues = read_beads_jsonl(merged)
        assert len(issues) == 2

    def test_replaces_by_id(self):
        existing = write_beads_jsonl([make_issue(id="bd-1", title="Old")])
        updates = [make_issue(id="bd-1", title="New", status="closed")]

        merged = merge_beads_jsonl(existing, updates)
        issues = read_beads_jsonl(merged)
        assert len(issues) == 1
        assert issues[0].title == "New"
        assert issues[0].status == "closed"


class TestGetReadyIssues:
    def test_returns_open(self):
        issues = [
            make_issue(id="bd-1", status="open"),
            make_issue(id="bd-2", status="in_progress"),
            make_issue(id="bd-3", status="closed"),
        ]
        ready = get_ready_issues(issues)
        assert len(ready) == 1
        assert ready[0].id == "bd-1"

    def test_filters_blocked(self):
        issues = [
            make_issue(id="bd-1", status="open"),
            make_issue(
                id="bd-2",
                status="open",
                dependencies=[
                    BeadsDependency(issue_id="bd-2", depends_on_id="bd-1", type="blocks")
                ],
            ),
        ]
        ready = get_ready_issues(issues)
        assert len(ready) == 1
        assert ready[0].id == "bd-1"

    def test_unblocks_when_closed(self):
        issues = [
            make_issue(id="bd-1", status="closed"),
            make_issue(
                id="bd-2",
                status="open",
                dependencies=[
                    BeadsDependency(issue_id="bd-2", depends_on_id="bd-1", type="blocks")
                ],
            ),
        ]
        ready = get_ready_issues(issues)
        assert len(ready) == 1
        assert ready[0].id == "bd-2"

    def test_filters_deferred(self):
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        issues = [
            make_issue(id="bd-1", status="open"),
            make_issue(id="bd-2", status="open", defer_until=future),
        ]
        ready = get_ready_issues(issues)
        assert len(ready) == 1
        assert ready[0].id == "bd-1"

    def test_filters_ephemeral(self):
        issues = [
            make_issue(id="bd-1", status="open"),
            make_issue(id="bd-2", status="open", ephemeral=True),
        ]
        ready = get_ready_issues(issues)
        assert len(ready) == 1
        assert ready[0].id == "bd-1"
