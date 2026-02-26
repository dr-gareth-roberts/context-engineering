"""
BEADS JSONL Format Support

Implements reading/writing of the BEADS JSONL format for agent context handoff.

BEADS is Steve Yegge's git-backed issue tracker for AI coding agents.
The JSONL format is the git-portable serialization layer that enables
agents to come and go while maintaining structured context.

This module bridges the Context Engineering Toolkit's ContextItem
format with BEADS issues, enabling:
- Serializing context state to BEADS JSONL for agent handoff
- Deserializing BEADS JSONL to pick up where another agent left off
- Tracking work items alongside context in a single format

Reference: https://github.com/steveyegge/beads
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from .core import ContextItem, ContextPack, estimate_tokens

# ─── BEADS Types ──────────────────────────────────────────────────────

BeadsStatus = Literal["open", "in_progress", "blocked", "deferred", "closed", "pinned", "hooked"]

BeadsIssueType = Literal[
    "bug", "feature", "task", "epic", "chore", "decision", "message", "molecule", "context"
]


@dataclass
class BeadsDependency:
    issue_id: str
    depends_on_id: str
    type: str  # "blocks", "parent-child", "related", etc.
    created_at: Optional[str] = None
    created_by: Optional[str] = None


@dataclass
class BeadsComment:
    issue_id: str
    author: str
    text: str
    created_at: str
    id: Optional[int] = None


@dataclass
class BeadsIssue:
    """A BEADS issue — the core record type in the JSONL format."""

    id: str
    title: str
    status: str  # BeadsStatus
    priority: int
    issue_type: str  # BeadsIssueType
    created_at: str
    updated_at: str

    description: Optional[str] = None
    design: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    notes: Optional[str] = None

    assignee: Optional[str] = None
    owner: Optional[str] = None

    closed_at: Optional[str] = None
    close_reason: Optional[str] = None
    due_at: Optional[str] = None
    defer_until: Optional[str] = None

    external_ref: Optional[str] = None
    source_system: Optional[str] = None

    metadata: Optional[Dict[str, Any]] = None
    compaction_level: Optional[int] = None

    labels: Optional[List[str]] = None
    dependencies: Optional[List[BeadsDependency]] = None
    comments: Optional[List[BeadsComment]] = None

    pinned: Optional[bool] = None
    ephemeral: Optional[bool] = None

    # Catch-all for additional BEADS fields
    extra: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict, excluding None values."""
        d: Dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if v is None or k == "extra":
                continue
            if k == "dependencies" and v:
                d[k] = [{kk: vv for kk, vv in dep.__dict__.items() if vv is not None} for dep in v]
            elif k == "comments" and v:
                d[k] = [{kk: vv for kk, vv in c.__dict__.items() if vv is not None} for c in v]
            else:
                d[k] = v
        if self.extra:
            d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeadsIssue":
        """Deserialize from a dict, storing unknown fields in extra."""
        known_fields = {f for f in cls.__dataclass_fields__}
        known_data = {}
        extra_data = {}

        for k, v in data.items():
            if k in known_fields:
                known_data[k] = v
            else:
                extra_data[k] = v

        # Parse dependencies
        if "dependencies" in known_data and known_data["dependencies"]:
            known_data["dependencies"] = [
                BeadsDependency(**dep) if isinstance(dep, dict) else dep
                for dep in known_data["dependencies"]
            ]

        # Parse comments
        if "comments" in known_data and known_data["comments"]:
            known_data["comments"] = [
                BeadsComment(**c) if isinstance(c, dict) else c for c in known_data["comments"]
            ]

        issue = cls(**known_data)
        if extra_data:
            issue.extra = extra_data
        return issue


# ─── BEADS JSONL Read/Write ───────────────────────────────────────────


def read_beads_jsonl(input_str: str) -> List[BeadsIssue]:
    """Parse a BEADS JSONL string into a list of issues.

    Each line is a self-contained JSON object.
    Blank lines and lines starting with # are skipped.
    """
    issues: List[BeadsIssue] = []

    for line in input_str.split("\n"):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue

        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, dict) and "id" in parsed:
                issues.append(BeadsIssue.from_dict(parsed))
        except (json.JSONDecodeError, TypeError):
            pass  # Skip malformed lines

    return issues


def write_beads_jsonl(issues: List[BeadsIssue]) -> str:
    """Serialize a list of BEADS issues to JSONL format."""
    return "\n".join(json.dumps(issue.to_dict()) for issue in issues)


# ─── ContextItem ↔ BeadsIssue Bridge ─────────────────────────────────


@dataclass
class BeadsBridgeOptions:
    """Options for bridging between ContextItems and BEADS issues."""

    agent: Optional[str] = None
    source_system: str = "context-engineering"
    default_status: str = "open"
    kind_to_issue_type: Optional[Dict[str, str]] = None
    kind_to_labels: Optional[Dict[str, List[str]]] = None


_DEFAULT_KIND_TO_ISSUE_TYPE: Dict[str, str] = {
    "system": "context",
    "tool": "context",
    "schema": "context",
    "memory": "context",
    "conversation": "context",
    "query": "context",
    "retrieval": "context",
    "task": "task",
    "bug": "bug",
    "feature": "feature",
}


def context_item_to_beads(
    item: ContextItem,
    options: Optional[BeadsBridgeOptions] = None,
) -> BeadsIssue:
    """Convert a ContextItem to a BEADS issue.

    The context item's content becomes the description, its kind maps
    to issue_type and labels, and its priority maps to BEADS priority
    (inverted: high context priority -> low BEADS priority number).
    """
    opts = options or BeadsBridgeOptions()
    now = datetime.now(timezone.utc).isoformat()
    kind_map = opts.kind_to_issue_type or _DEFAULT_KIND_TO_ISSUE_TYPE
    label_map = opts.kind_to_labels or {}

    # Map priority: ContextItem priority 10 (high) -> BEADS P0 (critical)
    priority_val = item.priority if item.priority is not None else 5.0
    beads_priority = max(0, min(4, 4 - int((priority_val / 10) * 4)))

    labels = []
    if item.kind:
        labels.append(f"kind:{item.kind}")
        if item.kind in label_map:
            labels.extend(label_map[item.kind])
    labels.append("context-engineering")

    metadata: Dict[str, Any] = {**(item.metadata or {})}
    metadata["_ce"] = {
        "kind": item.kind,
        "priority": item.priority,
        "recency": item.recency,
        "tokens": item.tokens,
        "score": item.score,
        "originalId": item.id,
    }

    return BeadsIssue(
        id=f"ce-{item.id}",
        title=item.id,
        description=item.content,
        status=opts.default_status,
        priority=beads_priority,
        issue_type=kind_map.get(item.kind or "", "context"),
        assignee=opts.agent,
        source_system=opts.source_system,
        labels=labels,
        created_at=now,
        updated_at=now,
        metadata=metadata,
    )


def beads_to_context_item(issue: BeadsIssue) -> ContextItem:
    """Convert a BEADS issue back to a ContextItem.

    Reads the _ce metadata extension to recover original context
    item properties. Falls back to inferring from BEADS fields.
    """
    ce_metadata = (issue.metadata or {}).get("_ce", {}) if issue.metadata else {}

    # Recover original ID
    original_id = ce_metadata.get("originalId")
    if not original_id:
        original_id = issue.id[3:] if issue.id.startswith("ce-") else issue.id

    # Recover kind from metadata or labels
    kind = ce_metadata.get("kind")
    if not kind and issue.labels:
        for label in issue.labels:
            if label.startswith("kind:"):
                kind = label[5:]
                break

    # Recover priority
    priority = ce_metadata.get("priority")
    if priority is None:
        priority = max(1, round(((4 - issue.priority) / 4) * 10))

    content = issue.description or issue.title
    tokens = ce_metadata.get("tokens") or estimate_tokens(content)

    # Strip _ce from metadata
    metadata = dict(issue.metadata) if issue.metadata else {}
    metadata.pop("_ce", None)

    return ContextItem(
        id=original_id,
        content=content,
        kind=kind,
        priority=priority,
        recency=ce_metadata.get("recency"),
        tokens=tokens,
        score=ce_metadata.get("score"),
        metadata=metadata if metadata else {},
    )


# ─── Agent Handoff Protocol ──────────────────────────────────────────


@dataclass
class HandoffOptions(BeadsBridgeOptions):
    """Options for creating a handoff."""

    session_id: Optional[str] = None
    include_dropped: bool = False
    handoff_notes: Optional[str] = None


@dataclass
class HandoffResult:
    """Result of creating a BEADS handoff."""

    jsonl: str
    issues: List[BeadsIssue]
    stats: Dict[str, Any]


def create_handoff(
    pack: ContextPack,
    options: Optional[HandoffOptions] = None,
) -> HandoffResult:
    """Create a BEADS JSONL handoff from a context pack.

    Converts the packed context into BEADS issues that another agent
    can pick up. Selected items become open issues, dropped items
    become deferred issues (if include_dropped is True).

    Example:
        pack = session.compile()
        handoff = create_handoff(pack, HandoffOptions(
            agent="agent-1",
            session_id="session-abc",
            include_dropped=True,
        ))
        with open(".beads/issues.jsonl", "w") as f:
            f.write(handoff.jsonl)
    """
    opts = options or HandoffOptions()
    now = datetime.now(timezone.utc).isoformat()
    issues: List[BeadsIssue] = []

    # Create manifest issue (the "handoff bead")
    manifest = BeadsIssue(
        id=f"ce-handoff-{hex(int(time.time() * 1000))[2:]}",
        title="Context Engineering Handoff",
        description=opts.handoff_notes or "Agent context handoff via Context Engineering Toolkit",
        status="pinned",
        priority=0,
        issue_type="message",
        assignee=opts.agent,
        source_system=opts.source_system,
        labels=["context-engineering", "handoff"],
        created_at=now,
        updated_at=now,
        metadata={
            "_ce_handoff": {
                "sessionId": opts.session_id,
                "totalTokens": pack.total_tokens,
                "selectedCount": len(pack.selected),
                "droppedCount": len(pack.dropped),
                "budget": {
                    "maxTokens": pack.budget.max_tokens,
                    "reserveTokens": pack.budget.reserve_tokens,
                },
                "createdAt": now,
            },
        },
    )
    issues.append(manifest)

    # Convert selected items to open issues
    bridge_opts = BeadsBridgeOptions(
        agent=opts.agent,
        source_system=opts.source_system,
        default_status="open",
        kind_to_issue_type=opts.kind_to_issue_type,
        kind_to_labels=opts.kind_to_labels,
    )
    for item in pack.selected:
        issue = context_item_to_beads(item, bridge_opts)
        issue.status = "open"
        issues.append(issue)

    # Convert dropped items to deferred issues
    deferred_count = 0
    if opts.include_dropped:
        for item in pack.dropped:
            issue = context_item_to_beads(item, bridge_opts)
            issue.status = "deferred"
            issue.defer_until = now
            issues.append(issue)
            deferred_count += 1

    return HandoffResult(
        jsonl=write_beads_jsonl(issues),
        issues=issues,
        stats={
            "totalIssues": len(issues),
            "contextIssues": len(issues) - 1,
            "activeItems": len(pack.selected),
            "deferredItems": deferred_count,
        },
    )


@dataclass
class PickupResult:
    """Result of picking up context from a BEADS handoff."""

    items: List[ContextItem]
    deferred: List[ContextItem]
    manifest: Optional[BeadsIssue]
    work_items: List[BeadsIssue]
    stats: Dict[str, Any]


def pickup_handoff(jsonl: str) -> PickupResult:
    """Pick up context from a BEADS JSONL handoff.

    Reads the JSONL, separates context items from work items,
    and recovers the original ContextItem format.

    Example:
        with open(".beads/issues.jsonl") as f:
            jsonl = f.read()
        pickup = pickup_handoff(jsonl)

        session = create_session(budget)
        session.set_items(pickup.items)
        result = session.compile()
    """
    issues = read_beads_jsonl(jsonl)

    items: List[ContextItem] = []
    deferred: List[ContextItem] = []
    work_items: List[BeadsIssue] = []
    manifest: Optional[BeadsIssue] = None

    for issue in issues:
        # Check if it's a handoff manifest
        if issue.id.startswith("ce-handoff-") or (
            issue.labels and "handoff" in issue.labels and issue.issue_type == "message"
        ):
            manifest = issue
            continue

        # Check if it's a context engineering item
        is_context = (
            issue.issue_type == "context"
            or issue.source_system == "context-engineering"
            or (issue.labels and "context-engineering" in issue.labels)
            or (issue.metadata and "_ce" in issue.metadata)
        )

        if is_context:
            context_item = beads_to_context_item(issue)
            if issue.status == "deferred":
                deferred.append(context_item)
            elif issue.status != "closed":
                items.append(context_item)
        else:
            work_items.append(issue)

    handoff_meta = {}
    if manifest and manifest.metadata:
        handoff_meta = manifest.metadata.get("_ce_handoff", {})

    return PickupResult(
        items=items,
        deferred=deferred,
        manifest=manifest,
        work_items=work_items,
        stats={
            "totalIssues": len(issues),
            "contextItems": len(items),
            "deferredItems": len(deferred),
            "workItems": len(work_items),
            "handoffSessionId": handoff_meta.get("sessionId"),
            "handoffBudget": handoff_meta.get("budget"),
        },
    )


# ─── Incremental BEADS Operations ────────────────────────────────────


def merge_beads_jsonl(existing: str, updates: List[BeadsIssue]) -> str:
    """Merge new issues into an existing BEADS JSONL string.

    Issues with the same ID are replaced; new issues are appended.
    """
    existing_issues = read_beads_jsonl(existing)
    existing_map = {i.id: i for i in existing_issues}

    for update in updates:
        existing_map[update.id] = update

    return write_beads_jsonl(list(existing_map.values()))


def get_ready_issues(issues: List[BeadsIssue]) -> List[BeadsIssue]:
    """Filter BEADS issues to get only "ready" items.

    Equivalent to `bd ready`. Returns issues that are:
    - Status is "open"
    - Not ephemeral
    - No unresolved blocking dependencies
    - defer_until is null or in the past
    """
    now = datetime.now(timezone.utc).isoformat()
    closed_ids = {i.id for i in issues if i.status == "closed"}

    ready = []
    for issue in issues:
        if issue.status != "open":
            continue
        if issue.ephemeral:
            continue
        if issue.defer_until and issue.defer_until > now:
            continue

        # Check blocking dependencies
        if issue.dependencies:
            blocked = False
            for dep in issue.dependencies:
                if dep.type in ("blocks", "parent-child"):
                    if dep.depends_on_id not in closed_ids:
                        blocked = True
                        break
            if blocked:
                continue

        ready.append(issue)

    return ready
