/**
 * BEADS JSONL Format Support
 *
 * Implements reading/writing of the BEADS (Bead-based Engineering and
 * Development System) JSONL format for agent context handoff.
 *
 * BEADS is Steve Yegge's git-backed issue tracker for AI coding agents.
 * The JSONL format is the git-portable serialization layer that enables
 * agents to come and go while maintaining structured context.
 *
 * This module bridges the Context Engineering Toolkit's ContextItem
 * format with BEADS issues, enabling:
 * - Serializing context state to BEADS JSONL for agent handoff
 * - Deserializing BEADS JSONL to pick up where another agent left off
 * - Tracking work items alongside context in a single format
 *
 * Reference: https://github.com/steveyegge/beads
 */

import type { ContextItem, ContextPack } from "./types.js";
import { estimateTokens } from "./estimate.js";

// ─── BEADS Types (subset relevant to context engineering) ────────────

export type BeadsStatus =
  | "open"
  | "in_progress"
  | "blocked"
  | "deferred"
  | "closed"
  | "pinned"
  | "hooked";

export type BeadsIssueType =
  | "bug"
  | "feature"
  | "task"
  | "epic"
  | "chore"
  | "decision"
  | "message"
  | "molecule"
  | "context";  // extension: context items stored as BEADS

export type BeadsDependencyType =
  | "blocks"
  | "parent-child"
  | "related"
  | "replies-to"
  | "supersedes"
  | "caused-by"
  | string;

export interface BeadsDependency {
  issue_id: string;
  depends_on_id: string;
  type: BeadsDependencyType;
  created_at?: string;
  created_by?: string;
}

export interface BeadsComment {
  id?: number;
  issue_id: string;
  author: string;
  text: string;
  created_at: string;
}

/**
 * A BEADS issue — the core record type in the JSONL format.
 *
 * We support the full read schema but only require the subset
 * needed for context engineering operations.
 */
export interface BeadsIssue {
  // Core identification
  id: string;

  // Content
  title: string;
  description?: string;
  design?: string;
  acceptance_criteria?: string;
  notes?: string;

  // Status & workflow
  status: BeadsStatus;
  priority: number;
  issue_type: BeadsIssueType;

  // Assignment
  assignee?: string;
  owner?: string;

  // Timestamps
  created_at: string;
  updated_at: string;
  closed_at?: string;
  close_reason?: string;

  // Scheduling
  due_at?: string;
  defer_until?: string;

  // External
  external_ref?: string;
  source_system?: string;

  // Metadata (arbitrary JSON)
  metadata?: Record<string, unknown>;

  // Compaction
  compaction_level?: number;

  // Relations (populated on export)
  labels?: string[];
  dependencies?: BeadsDependency[];
  comments?: BeadsComment[];

  // Context engineering extensions (stored in metadata)
  // These are convenience fields that map to/from metadata
  pinned?: boolean;
  ephemeral?: boolean;

  // Allow additional fields from the full BEADS spec
  [key: string]: unknown;
}

// ─── BEADS JSONL Read/Write ──────────────────────────────────────────

/**
 * Parse a BEADS JSONL string into an array of issues.
 * Each line is a self-contained JSON object.
 * Blank lines and lines starting with # are skipped.
 *
 * @param input - BEADS JSONL string to parse
 * @returns Array of parsed BEADS issues
 *
 * @example
 * ```ts
 * const jsonl = fs.readFileSync(".beads/issues.jsonl", "utf-8");
 * const issues = readBeadsJSONL(jsonl);
 * console.log(issues.length);
 * ```
 */
export function readBeadsJSONL(input: string): BeadsIssue[] {
  const issues: BeadsIssue[] = [];

  for (const line of input.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && typeof parsed === "object" && parsed.id) {
        issues.push(parsed as BeadsIssue);
      }
    } catch {
      // Skip malformed lines (BEADS spec tolerates this)
    }
  }

  return issues;
}

/**
 * Serialize an array of BEADS issues to JSONL format.
 * One JSON object per line, no trailing newline.
 *
 * @param issues - Array of BEADS issues to serialize
 * @returns JSONL string with one issue per line
 *
 * @example
 * ```ts
 * const jsonl = writeBeadsJSONL(issues);
 * fs.writeFileSync(".beads/issues.jsonl", jsonl);
 * ```
 */
export function writeBeadsJSONL(issues: BeadsIssue[]): string {
  return issues
    .map(issue => JSON.stringify(issue))
    .join("\n");
}

// ─── ContextItem ↔ BeadsIssue Bridge ─────────────────────────────────

export interface BeadsBridgeOptions {
  /** Agent identity for assignee field */
  agent?: string;
  /** Source system identifier */
  sourceSystem?: string;
  /** Default status for new issues */
  defaultStatus?: BeadsStatus;
  /** Map context item kinds to BEADS issue types */
  kindToIssueType?: Record<string, BeadsIssueType>;
  /** Map context item kinds to BEADS labels */
  kindToLabels?: Record<string, string[]>;
}

const DEFAULT_KIND_TO_ISSUE_TYPE: Record<string, BeadsIssueType> = {
  system: "context",
  tool: "context",
  schema: "context",
  memory: "context",
  conversation: "context",
  query: "context",
  retrieval: "context",
  task: "task",
  bug: "bug",
  feature: "feature",
};

/**
 * Convert a ContextItem to a BEADS issue.
 *
 * The context item's content becomes the description, its kind maps
 * to issue_type and labels, and its priority maps to BEADS priority
 * (inverted: high context priority → low BEADS priority number).
 *
 * @param item - The context item to convert
 * @param options - Bridge options for agent, source system, and kind mapping
 *
 * @example
 * ```ts
 * const issue = contextItemToBeads(
 *   { id: "doc1", content: "API docs...", kind: "system", priority: 10 },
 *   { agent: "agent-1" },
 * );
 * ```
 */
export function contextItemToBeads(
  item: ContextItem,
  options: BeadsBridgeOptions = {},
): BeadsIssue {
  const now = new Date().toISOString();
  const kindMap = options.kindToIssueType ?? DEFAULT_KIND_TO_ISSUE_TYPE;
  const labelMap = options.kindToLabels ?? {};

  // Map priority: ContextItem priority 10 (high) → BEADS P0 (critical)
  // ContextItem priority 1 (low) → BEADS P4 (backlog)
  const beadsPriority = Math.max(0, Math.min(4,
    4 - Math.floor(((item.priority ?? 5) / 10) * 4)
  ));

  const labels: string[] = [];
  if (item.kind) {
    labels.push(`kind:${item.kind}`);
    if (labelMap[item.kind]) {
      labels.push(...labelMap[item.kind]);
    }
  }
  labels.push("context-engineering");

  return {
    id: `ce-${item.id}`,
    title: item.id,
    description: item.content,
    status: options.defaultStatus ?? "open",
    priority: beadsPriority,
    issue_type: kindMap[item.kind ?? ""] ?? "context",
    assignee: options.agent,
    source_system: options.sourceSystem ?? "context-engineering",
    labels,
    created_at: now,
    updated_at: now,
    metadata: {
      ...item.metadata,
      _ce: {
        kind: item.kind,
        priority: item.priority,
        recency: item.recency,
        tokens: item.tokens,
        score: item.score,
        originalId: item.id,
      },
    },
  };
}

/**
 * Convert a BEADS issue back to a ContextItem.
 *
 * Reads the _ce metadata extension to recover original context
 * item properties. Falls back to inferring from BEADS fields.
 *
 * @param issue - The BEADS issue to convert back to a context item
 */
export function beadsToContextItem(issue: BeadsIssue): ContextItem {
  const ceMetadata = (issue.metadata as Record<string, unknown>)?._ce as Record<string, unknown> | undefined;

  // Recover original ID: strip ce- prefix if present
  const originalId = (ceMetadata?.originalId as string) ??
    (issue.id.startsWith("ce-") ? issue.id.slice(3) : issue.id);

  // Recover kind from metadata or labels
  let kind = ceMetadata?.kind as string | undefined;
  if (!kind && issue.labels) {
    const kindLabel = issue.labels.find(l => l.startsWith("kind:"));
    if (kindLabel) kind = kindLabel.slice(5);
  }

  // Recover priority: BEADS P0 → priority 10, P4 → priority 1
  const priority = (ceMetadata?.priority as number) ??
    Math.max(1, Math.round(((4 - issue.priority) / 4) * 10));

  const content = issue.description ?? issue.title;
  const tokens = (ceMetadata?.tokens as number) ?? estimateTokens(content);

  // Strip _ce from metadata to avoid recursion
  const metadata = issue.metadata ? { ...issue.metadata } : undefined;
  if (metadata) delete metadata._ce;

  return {
    id: originalId,
    content,
    kind,
    priority,
    recency: ceMetadata?.recency as number | undefined,
    tokens,
    score: ceMetadata?.score as number | undefined,
    metadata: metadata && Object.keys(metadata).length > 0 ? metadata : undefined,
  };
}

// ─── Agent Handoff Protocol ──────────────────────────────────────────

export interface HandoffOptions extends BeadsBridgeOptions {
  /** Session identifier for traceability */
  sessionId?: string;
  /** Include dropped items as deferred issues */
  includeDropped?: boolean;
  /** Additional notes for the handoff */
  handoffNotes?: string;
}

export interface HandoffResult {
  /** BEADS JSONL string ready to write to .beads/issues.jsonl */
  jsonl: string;
  /** Parsed issues for programmatic access */
  issues: BeadsIssue[];
  /** Summary statistics */
  stats: {
    totalIssues: number;
    contextIssues: number;
    activeItems: number;
    deferredItems: number;
  };
}

/**
 * Create a BEADS JSONL handoff from a context pack.
 *
 * Converts the packed context into BEADS issues that another agent
 * can pick up. Selected items become open issues, dropped items
 * become deferred issues (if includeDropped is true).
 *
 * @param pack - The context pack to convert to a handoff
 * @param options - Handoff options including agent identity and session ID
 * @returns HandoffResult with JSONL string, parsed issues, and stats
 *
 * @example
 * ```ts
 * const pack = session.compile();
 * const handoff = createHandoff(pack, {
 *   agent: "agent-1",
 *   sessionId: "session-abc",
 *   includeDropped: true,
 * });
 * fs.writeFileSync(".beads/issues.jsonl", handoff.jsonl);
 * // git add . && git push
 * ```
 */
export function createHandoff(
  pack: ContextPack,
  options: HandoffOptions = {},
): HandoffResult {
  const issues: BeadsIssue[] = [];
  const now = new Date().toISOString();

  // Create a manifest issue (the "handoff bead")
  const manifestIssue: BeadsIssue = {
    id: `ce-handoff-${Date.now().toString(36)}`,
    title: "Context Engineering Handoff",
    description: options.handoffNotes ?? "Agent context handoff via Context Engineering Toolkit",
    status: "pinned",
    priority: 0,
    issue_type: "message",
    assignee: options.agent,
    source_system: options.sourceSystem ?? "context-engineering",
    labels: ["context-engineering", "handoff"],
    created_at: now,
    updated_at: now,
    metadata: {
      _ce_handoff: {
        sessionId: options.sessionId,
        totalTokens: pack.totalTokens,
        selectedCount: pack.selected.length,
        droppedCount: pack.dropped.length,
        budget: pack.budget,
        stats: pack.stats,
        createdAt: now,
      },
    },
  };
  issues.push(manifestIssue);

  // Convert selected items to open issues
  for (const item of pack.selected) {
    const issue = contextItemToBeads(item, options);
    issue.status = "open";
    issues.push(issue);
  }

  // Convert dropped items to deferred issues
  if (options.includeDropped) {
    for (const item of pack.dropped) {
      const issue = contextItemToBeads(item, options);
      issue.status = "deferred";
      issue.defer_until = now; // immediately available on pickup
      issues.push(issue);
    }
  }

  return {
    jsonl: writeBeadsJSONL(issues),
    issues,
    stats: {
      totalIssues: issues.length,
      contextIssues: issues.length - 1, // exclude manifest
      activeItems: pack.selected.length,
      deferredItems: options.includeDropped ? pack.dropped.length : 0,
    },
  };
}

export interface PickupResult {
  /** Recovered context items (from open issues) */
  items: ContextItem[];
  /** Deferred context items (from deferred issues) */
  deferred: ContextItem[];
  /** The handoff manifest, if found */
  manifest: BeadsIssue | null;
  /** Non-context issues (tasks, bugs, etc.) */
  workItems: BeadsIssue[];
  /** Summary statistics */
  stats: {
    totalIssues: number;
    contextItems: number;
    deferredItems: number;
    workItems: number;
    handoffSessionId?: string;
    handoffBudget?: unknown;
  };
}

/**
 * Pick up context from a BEADS JSONL handoff.
 *
 * Reads the JSONL, separates context items from work items,
 * and recovers the original ContextItem format.
 *
 * @param jsonl - BEADS JSONL string to parse
 * @returns PickupResult with recovered context items, deferred items, and work items
 *
 * @example
 * ```ts
 * const jsonl = fs.readFileSync(".beads/issues.jsonl", "utf-8");
 * const pickup = pickupHandoff(jsonl);
 *
 * const session = createSession({ budget: { maxTokens: 8000 } });
 * session.setItems(pickup.items);
 * const result = session.compile();
 * ```
 */
export function pickupHandoff(jsonl: string): PickupResult {
  const issues = readBeadsJSONL(jsonl);

  const items: ContextItem[] = [];
  const deferred: ContextItem[] = [];
  const workItems: BeadsIssue[] = [];
  let manifest: BeadsIssue | null = null;

  for (const issue of issues) {
    // Check if it's a handoff manifest
    if (
      issue.id.startsWith("ce-handoff-") ||
      (issue.labels?.includes("handoff") && issue.issue_type === "message")
    ) {
      manifest = issue;
      continue;
    }

    // Check if it's a context engineering item
    const isContextItem =
      issue.issue_type === "context" ||
      issue.source_system === "context-engineering" ||
      issue.labels?.includes("context-engineering") ||
      (issue.metadata as Record<string, unknown>)?._ce !== undefined;

    if (isContextItem) {
      const contextItem = beadsToContextItem(issue);
      if (issue.status === "deferred") {
        deferred.push(contextItem);
      } else if (issue.status !== "closed") {
        items.push(contextItem);
      }
    } else {
      workItems.push(issue);
    }
  }

  const handoffMeta = (manifest?.metadata as Record<string, unknown>)?._ce_handoff as Record<string, unknown> | undefined;

  return {
    items,
    deferred,
    manifest,
    workItems,
    stats: {
      totalIssues: issues.length,
      contextItems: items.length,
      deferredItems: deferred.length,
      workItems: workItems.length,
      handoffSessionId: handoffMeta?.sessionId as string | undefined,
      handoffBudget: handoffMeta?.budget,
    },
  };
}

// ─── Incremental BEADS Operations ────────────────────────────────────

/**
 * Merge new issues into an existing BEADS JSONL string.
 * Issues with the same ID are replaced; new issues are appended.
 *
 * @param existing - Existing BEADS JSONL string
 * @param updates - New or updated issues to merge in
 * @returns Merged JSONL string
 */
export function mergeBeadsJSONL(
  existing: string,
  updates: BeadsIssue[],
): string {
  const existingIssues = readBeadsJSONL(existing);
  const existingMap = new Map(existingIssues.map(i => [i.id, i]));

  for (const update of updates) {
    existingMap.set(update.id, update);
  }

  return writeBeadsJSONL(Array.from(existingMap.values()));
}

/**
 * Filter BEADS issues to get only "ready" items — the equivalent
 * of `bd ready`. Returns issues that are:
 * - Status is "open"
 * - Not ephemeral
 * - No unresolved blocking dependencies
 * - defer_until is null or in the past
 *
 * @param issues - Array of BEADS issues to filter
 * @returns Issues that are ready to be worked on
 */
export function getReadyIssues(issues: BeadsIssue[]): BeadsIssue[] {
  const now = new Date().toISOString();
  const closedIds = new Set(
    issues.filter(i => i.status === "closed").map(i => i.id)
  );

  return issues.filter(issue => {
    if (issue.status !== "open") return false;
    if (issue.ephemeral) return false;

    // Check defer_until
    if (issue.defer_until && issue.defer_until > now) return false;

    // Check blocking dependencies
    if (issue.dependencies) {
      const blocked = issue.dependencies.some(dep => {
        if (dep.type !== "blocks" && dep.type !== "parent-child") return false;
        return !closedIds.has(dep.depends_on_id);
      });
      if (blocked) return false;
    }

    return true;
  });
}
