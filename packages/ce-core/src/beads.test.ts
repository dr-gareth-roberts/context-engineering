import { describe, expect, it } from "vitest";
import {
  readBeadsJSONL,
  writeBeadsJSONL,
  contextItemToBeads,
  beadsToContextItem,
  createHandoff,
  pickupHandoff,
  mergeBeadsJSONL,
  getReadyIssues,
} from "./beads.js";
import type { ContextItem, ContextPack, Budget } from "./types.js";
import type { BeadsIssue } from "./beads.js";

function makeItem(id: string, kind: string, priority: number, tokens: number): ContextItem {
  return { id, content: `content-${id}`, kind, priority, tokens };
}

function makePack(items: ContextItem[], dropped: ContextItem[] = []): ContextPack {
  const budget: Budget = { maxTokens: 500 };
  return {
    budget,
    selected: items,
    dropped,
    totalTokens: items.reduce((s, i) => s + (i.tokens ?? 0), 0),
  };
}

// ─── readBeadsJSONL / writeBeadsJSONL ────────────────────────────────

describe("readBeadsJSONL", () => {
  it("parses valid JSONL", () => {
    const jsonl = [
      JSON.stringify({ id: "bd-1", title: "Test", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" }),
      JSON.stringify({ id: "bd-2", title: "Test 2", status: "closed", priority: 1, issue_type: "bug", created_at: "2025-01-01", updated_at: "2025-01-01" }),
    ].join("\n");

    const issues = readBeadsJSONL(jsonl);
    expect(issues).toHaveLength(2);
    expect(issues[0].id).toBe("bd-1");
    expect(issues[1].id).toBe("bd-2");
  });

  it("skips blank lines and comments", () => {
    const jsonl = [
      "# This is a comment",
      "",
      JSON.stringify({ id: "bd-1", title: "Test", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" }),
      "",
      "# Another comment",
    ].join("\n");

    const issues = readBeadsJSONL(jsonl);
    expect(issues).toHaveLength(1);
  });

  it("skips malformed lines", () => {
    const jsonl = [
      "not json",
      JSON.stringify({ id: "bd-1", title: "Test", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" }),
      "{bad json",
    ].join("\n");

    const issues = readBeadsJSONL(jsonl);
    expect(issues).toHaveLength(1);
  });

  it("skips objects without id", () => {
    const jsonl = [
      JSON.stringify({ title: "No ID" }),
      JSON.stringify({ id: "bd-1", title: "Has ID", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" }),
    ].join("\n");

    const issues = readBeadsJSONL(jsonl);
    expect(issues).toHaveLength(1);
    expect(issues[0].id).toBe("bd-1");
  });

  it("handles empty input", () => {
    expect(readBeadsJSONL("")).toHaveLength(0);
    expect(readBeadsJSONL("\n\n")).toHaveLength(0);
  });
});

describe("writeBeadsJSONL", () => {
  it("serializes issues to JSONL", () => {
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "A", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      { id: "bd-2", title: "B", status: "closed", priority: 1, issue_type: "bug", created_at: "2025-01-01", updated_at: "2025-01-01" },
    ];

    const jsonl = writeBeadsJSONL(issues);
    const lines = jsonl.split("\n");
    expect(lines).toHaveLength(2);
    expect(JSON.parse(lines[0]).id).toBe("bd-1");
    expect(JSON.parse(lines[1]).id).toBe("bd-2");
  });

  it("roundtrips through read/write", () => {
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "A", status: "open", priority: 2, issue_type: "task", labels: ["test"], created_at: "2025-01-01", updated_at: "2025-01-01" },
    ];

    const jsonl = writeBeadsJSONL(issues);
    const parsed = readBeadsJSONL(jsonl);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].id).toBe("bd-1");
    expect(parsed[0].labels).toEqual(["test"]);
  });
});

// ─── ContextItem ↔ BeadsIssue Bridge ─────────────────────────────────

describe("contextItemToBeads", () => {
  it("converts a context item to a BEADS issue", () => {
    const item = makeItem("sys-prompt", "system", 10, 100);
    const issue = contextItemToBeads(item);

    expect(issue.id).toBe("ce-sys-prompt");
    expect(issue.title).toBe("sys-prompt");
    expect(issue.description).toBe("content-sys-prompt");
    expect(issue.issue_type).toBe("context");
    expect(issue.source_system).toBe("context-engineering");
    expect(issue.labels).toContain("kind:system");
    expect(issue.labels).toContain("context-engineering");
  });

  it("maps high priority to low BEADS priority number", () => {
    const high = contextItemToBeads(makeItem("a", "system", 10, 50));
    const low = contextItemToBeads(makeItem("b", "system", 1, 50));

    expect(high.priority).toBeLessThan(low.priority);
  });

  it("stores original context metadata in _ce extension", () => {
    const item: ContextItem = {
      id: "test",
      content: "hello",
      kind: "memory",
      priority: 7,
      recency: 0.8,
      tokens: 50,
      score: 6.5,
    };

    const issue = contextItemToBeads(item);
    const ce = (issue.metadata as Record<string, unknown>)._ce as Record<string, unknown>;

    expect(ce.kind).toBe("memory");
    expect(ce.priority).toBe(7);
    expect(ce.recency).toBe(0.8);
    expect(ce.tokens).toBe(50);
    expect(ce.originalId).toBe("test");
  });

  it("respects bridge options", () => {
    const item = makeItem("a", "system", 5, 50);
    const issue = contextItemToBeads(item, {
      agent: "agent-007",
      sourceSystem: "my-app",
      defaultStatus: "pinned",
    });

    expect(issue.assignee).toBe("agent-007");
    expect(issue.source_system).toBe("my-app");
    expect(issue.status).toBe("pinned");
  });
});

describe("beadsToContextItem", () => {
  it("recovers original context item from BEADS issue", () => {
    const original = makeItem("sys-prompt", "system", 10, 100);
    const issue = contextItemToBeads(original);
    const recovered = beadsToContextItem(issue);

    expect(recovered.id).toBe("sys-prompt");
    expect(recovered.content).toBe("content-sys-prompt");
    expect(recovered.kind).toBe("system");
    expect(recovered.priority).toBe(10);
    expect(recovered.tokens).toBe(100);
  });

  it("infers kind from labels when _ce is missing", () => {
    const issue: BeadsIssue = {
      id: "bd-test",
      title: "Test Issue",
      description: "Some content",
      status: "open",
      priority: 2,
      issue_type: "context",
      labels: ["kind:retrieval"],
      created_at: "2025-01-01",
      updated_at: "2025-01-01",
    };

    const item = beadsToContextItem(issue);
    expect(item.kind).toBe("retrieval");
  });

  it("infers priority from BEADS priority when _ce is missing", () => {
    const issue: BeadsIssue = {
      id: "bd-test",
      title: "Test",
      description: "Content",
      status: "open",
      priority: 0, // P0 = highest
      issue_type: "task",
      created_at: "2025-01-01",
      updated_at: "2025-01-01",
    };

    const item = beadsToContextItem(issue);
    expect(item.priority).toBe(10); // High priority
  });

  it("roundtrips context item through BEADS", () => {
    const original: ContextItem = {
      id: "my-item",
      content: "important context",
      kind: "memory",
      priority: 7,
      recency: 0.9,
      tokens: 42,
    };

    const issue = contextItemToBeads(original);
    const recovered = beadsToContextItem(issue);

    expect(recovered.id).toBe(original.id);
    expect(recovered.content).toBe(original.content);
    expect(recovered.kind).toBe(original.kind);
    expect(recovered.priority).toBe(original.priority);
    expect(recovered.recency).toBe(original.recency);
    expect(recovered.tokens).toBe(original.tokens);
  });
});

// ─── Agent Handoff / Pickup ──────────────────────────────────────────

describe("createHandoff", () => {
  it("creates JSONL from a context pack", () => {
    const pack = makePack([
      makeItem("sys", "system", 10, 100),
      makeItem("doc", "retrieval", 7, 50),
    ]);

    const result = createHandoff(pack);

    expect(result.issues.length).toBe(3); // manifest + 2 items
    expect(result.stats.activeItems).toBe(2);
    expect(result.stats.deferredItems).toBe(0);
    expect(result.jsonl).toBeTruthy();
  });

  it("includes dropped items when requested", () => {
    const pack = makePack(
      [makeItem("sys", "system", 10, 100)],
      [makeItem("low", "memory", 2, 50)],
    );

    const result = createHandoff(pack, { includeDropped: true });

    expect(result.stats.activeItems).toBe(1);
    expect(result.stats.deferredItems).toBe(1);
    expect(result.issues.length).toBe(3); // manifest + 1 active + 1 deferred
  });

  it("includes handoff metadata in manifest", () => {
    const pack = makePack([makeItem("a", "system", 10, 100)]);

    const result = createHandoff(pack, {
      agent: "agent-1",
      sessionId: "session-xyz",
      handoffNotes: "Completed phase 1",
    });

    const manifest = result.issues[0];
    expect(manifest.id).toMatch(/^ce-handoff-/);
    expect(manifest.status).toBe("pinned");
    expect(manifest.description).toBe("Completed phase 1");

    const meta = (manifest.metadata as Record<string, unknown>)._ce_handoff as Record<string, unknown>;
    expect(meta.sessionId).toBe("session-xyz");
    expect(meta.totalTokens).toBe(100);
  });
});

describe("pickupHandoff", () => {
  it("recovers context items from handoff JSONL", () => {
    const pack = makePack([
      makeItem("sys", "system", 10, 100),
      makeItem("doc", "retrieval", 7, 50),
    ]);

    const handoff = createHandoff(pack, { agent: "agent-1" });
    const pickup = pickupHandoff(handoff.jsonl);

    expect(pickup.items).toHaveLength(2);
    expect(pickup.items[0].id).toBe("sys");
    expect(pickup.items[1].id).toBe("doc");
    expect(pickup.manifest).not.toBeNull();
  });

  it("separates deferred items", () => {
    const pack = makePack(
      [makeItem("active", "system", 10, 100)],
      [makeItem("deferred", "memory", 2, 50)],
    );

    const handoff = createHandoff(pack, { includeDropped: true });
    const pickup = pickupHandoff(handoff.jsonl);

    expect(pickup.items).toHaveLength(1);
    expect(pickup.items[0].id).toBe("active");
    expect(pickup.deferred).toHaveLength(1);
    expect(pickup.deferred[0].id).toBe("deferred");
  });

  it("separates work items from context items", () => {
    const jsonl = [
      JSON.stringify({
        id: "ce-handoff-test",
        title: "Handoff",
        status: "pinned",
        priority: 0,
        issue_type: "message",
        labels: ["handoff"],
        created_at: "2025-01-01",
        updated_at: "2025-01-01",
        metadata: { _ce_handoff: { sessionId: "s1" } },
      }),
      JSON.stringify({
        id: "ce-sys",
        title: "sys",
        description: "System prompt",
        status: "open",
        priority: 0,
        issue_type: "context",
        source_system: "context-engineering",
        labels: ["context-engineering", "kind:system"],
        created_at: "2025-01-01",
        updated_at: "2025-01-01",
        metadata: { _ce: { originalId: "sys", kind: "system", priority: 10, tokens: 50 } },
      }),
      JSON.stringify({
        id: "bd-task-1",
        title: "Fix the bug",
        status: "open",
        priority: 1,
        issue_type: "bug",
        created_at: "2025-01-01",
        updated_at: "2025-01-01",
      }),
    ].join("\n");

    const pickup = pickupHandoff(jsonl);
    expect(pickup.items).toHaveLength(1);
    expect(pickup.items[0].id).toBe("sys");
    expect(pickup.workItems).toHaveLength(1);
    expect(pickup.workItems[0].id).toBe("bd-task-1");
    expect(pickup.stats.handoffSessionId).toBe("s1");
  });

  it("full roundtrip: pack → handoff → pickup → items", () => {
    const original = [
      makeItem("sys", "system", 10, 100),
      makeItem("mem", "memory", 6, 80),
      makeItem("query", "query", 8, 50),
    ];

    const pack = makePack(original);
    const handoff = createHandoff(pack, {
      agent: "agent-1",
      sessionId: "round-trip-test",
      includeDropped: false,
    });

    const pickup = pickupHandoff(handoff.jsonl);

    expect(pickup.items).toHaveLength(3);
    for (const orig of original) {
      const recovered = pickup.items.find(i => i.id === orig.id);
      expect(recovered).toBeDefined();
      expect(recovered!.content).toBe(orig.content);
      expect(recovered!.kind).toBe(orig.kind);
      expect(recovered!.priority).toBe(orig.priority);
      expect(recovered!.tokens).toBe(orig.tokens);
    }
  });

  it("handles empty JSONL", () => {
    const pickup = pickupHandoff("");
    expect(pickup.items).toHaveLength(0);
    expect(pickup.deferred).toHaveLength(0);
    expect(pickup.manifest).toBeNull();
  });
});

// ─── Incremental Operations ──────────────────────────────────────────

describe("mergeBeadsJSONL", () => {
  it("merges new issues into existing JSONL", () => {
    const existing = writeBeadsJSONL([
      { id: "bd-1", title: "A", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
    ]);

    const updates: BeadsIssue[] = [
      { id: "bd-2", title: "B", status: "open", priority: 1, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
    ];

    const merged = mergeBeadsJSONL(existing, updates);
    const issues = readBeadsJSONL(merged);
    expect(issues).toHaveLength(2);
  });

  it("replaces existing issues by id", () => {
    const existing = writeBeadsJSONL([
      { id: "bd-1", title: "Old", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
    ]);

    const updates: BeadsIssue[] = [
      { id: "bd-1", title: "New", status: "closed", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-02" },
    ];

    const merged = mergeBeadsJSONL(existing, updates);
    const issues = readBeadsJSONL(merged);
    expect(issues).toHaveLength(1);
    expect(issues[0].title).toBe("New");
    expect(issues[0].status).toBe("closed");
  });
});

describe("getReadyIssues", () => {
  it("returns open non-blocked issues", () => {
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "Ready", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      { id: "bd-2", title: "In Progress", status: "in_progress", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      { id: "bd-3", title: "Closed", status: "closed", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
    ];

    const ready = getReadyIssues(issues);
    expect(ready).toHaveLength(1);
    expect(ready[0].id).toBe("bd-1");
  });

  it("filters out blocked issues", () => {
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "Blocker", status: "open", priority: 1, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      {
        id: "bd-2", title: "Blocked", status: "open", priority: 2, issue_type: "task",
        created_at: "2025-01-01", updated_at: "2025-01-01",
        dependencies: [{ issue_id: "bd-2", depends_on_id: "bd-1", type: "blocks" }],
      },
    ];

    const ready = getReadyIssues(issues);
    expect(ready).toHaveLength(1);
    expect(ready[0].id).toBe("bd-1");
  });

  it("unblocks when blocker is closed", () => {
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "Done", status: "closed", priority: 1, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      {
        id: "bd-2", title: "Was Blocked", status: "open", priority: 2, issue_type: "task",
        created_at: "2025-01-01", updated_at: "2025-01-01",
        dependencies: [{ issue_id: "bd-2", depends_on_id: "bd-1", type: "blocks" }],
      },
    ];

    const ready = getReadyIssues(issues);
    expect(ready).toHaveLength(1);
    expect(ready[0].id).toBe("bd-2");
  });

  it("filters out deferred issues", () => {
    const future = new Date(Date.now() + 86400000).toISOString();
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "Ready", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      { id: "bd-2", title: "Deferred", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01", defer_until: future },
    ];

    const ready = getReadyIssues(issues);
    expect(ready).toHaveLength(1);
    expect(ready[0].id).toBe("bd-1");
  });

  it("filters out ephemeral issues", () => {
    const issues: BeadsIssue[] = [
      { id: "bd-1", title: "Normal", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01" },
      { id: "bd-2", title: "Ephemeral", status: "open", priority: 2, issue_type: "task", created_at: "2025-01-01", updated_at: "2025-01-01", ephemeral: true },
    ];

    const ready = getReadyIssues(issues);
    expect(ready).toHaveLength(1);
    expect(ready[0].id).toBe("bd-1");
  });
});
