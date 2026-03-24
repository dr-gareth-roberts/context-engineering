import type { ContextItem } from "@context-engineering/core";
import type { ContextQuality } from "@context-engineering/core";

export interface Snapshot {
  id: string;
  name: string;
  items: ContextItem[];
  createdAt: number;
  parentId: string | null;
  branchName: string;
  metadata?: Record<string, unknown>;
  quality?: ContextQuality;
}

export interface Branch {
  name: string;
  headSnapshotId: string;
  createdAt: number;
  parentBranch: string | null;
  forkPoint: string | null;
}

export type MergeStrategy =
  | "union"
  | "intersection"
  | "best-quality"
  | "highest-priority"
  | "manual";

export interface MergeOptions {
  strategy: MergeStrategy;
  /** For "manual" strategy: function that picks items from both branches */
  resolver?: (ours: ContextItem[], theirs: ContextItem[]) => ContextItem[];
  /** For "best-quality": which quality dimension to optimize */
  qualityDimension?:
    | "density"
    | "diversity"
    | "freshness"
    | "redundancy"
    | "overall";
}

export interface MergeResult {
  items: ContextItem[];
  strategy: MergeStrategy;
  fromBranch: string;
  intoBranch: string;
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
}

export interface BranchComparison {
  branch1: string;
  branch2: string;
  onlyInBranch1: ContextItem[];
  onlyInBranch2: ContextItem[];
  common: ContextItem[];
  modified: Array<{
    id: string;
    branch1Content: string;
    branch2Content: string;
  }>;
  quality1?: ContextQuality;
  quality2?: ContextQuality;
}

export interface TimelineOptions {
  /** Default branch name */
  defaultBranch?: string;
  /** Auto-snapshot on every item change */
  autoSnapshot?: boolean;
  /** Max snapshots to retain (oldest pruned) */
  maxSnapshots?: number;
}

export interface TimelineState {
  branches: Branch[];
  snapshots: Snapshot[];
  currentBranch: string;
}

export interface Timeline {
  /** Get all items on the current branch */
  getItems(): ContextItem[];
  /** Set items on the current branch (creates implicit snapshot if autoSnapshot) */
  setItems(items: ContextItem[]): void;
  /** Add items to the current branch */
  addItems(...items: ContextItem[]): void;
  /** Remove items by ID */
  removeItems(...ids: string[]): void;

  /** Create a named checkpoint on the current branch */
  checkpoint(name: string, metadata?: Record<string, unknown>): Snapshot;
  /** Rewind the current branch to a named checkpoint or snapshot ID */
  rewind(nameOrId: string): void;

  /** Create a new branch from the current state (or a specific snapshot) */
  fork(branchName: string, fromSnapshot?: string): Branch;
  /** Switch to a different branch */
  checkout(branchName: string): void;
  /** Get current branch name */
  currentBranch(): string;
  /** List all branches */
  listBranches(): Branch[];

  /** Compare two branches */
  compare(branch1: string, branch2: string): BranchComparison;
  /** Merge another branch into the current branch */
  merge(fromBranch: string, options?: MergeOptions): MergeResult;

  /** Get the full history of the current branch (all snapshots) */
  history(): Snapshot[];
  /** Get a specific snapshot by name or ID */
  getSnapshot(nameOrId: string): Snapshot | null;

  /** Export the entire timeline state for persistence */
  exportState(): TimelineState;
  /** Import a previously exported timeline state */
  importState(state: TimelineState): void;
}
