import type { MemoryItem } from "@context-engineering/core";
import Database from "better-sqlite3";
import type { MemoryQuery, MemoryStore } from "./types.js";
import { applyQueryFilter, normalizeMemoryItem } from "./utils.js";

interface SqliteStoreOptions {
  tableName?: string;
}

type DatabaseInstance = ReturnType<typeof Database>;

interface SqliteRow {
  id: string;
  content: string;
  created_at: string;
  updated_at: string | null;
  salience: number | null;
  ttl_seconds: number | null;
  metadata_json: string | null;
  last_accessed_at: string | null;
  is_summary: number | null;
  embedding_json: string | null;
  links_json: string | null;
}

function rowToItem(row: SqliteRow): MemoryItem {
  const item: MemoryItem = {
    id: row.id,
    content: row.content,
    createdAt: row.created_at,
    updatedAt: row.updated_at ?? undefined,
    salience: row.salience ?? undefined,
    ttlSeconds: row.ttl_seconds ?? undefined,
    metadata: row.metadata_json ? JSON.parse(row.metadata_json) : undefined,
  };
  if (row.last_accessed_at !== null) item.lastAccessedAt = row.last_accessed_at;
  if (row.is_summary !== null) item.isSummary = Boolean(row.is_summary);
  if (row.embedding_json !== null) {
    item.embedding = JSON.parse(row.embedding_json) as number[];
  }
  if (row.links_json !== null) {
    item.links = JSON.parse(row.links_json) as string[];
  }
  return item;
}

export class SqliteStore implements MemoryStore {
  private db: DatabaseInstance;
  private tableName: string;
  private closed = false;

  constructor(databasePath: string, options: SqliteStoreOptions = {}) {
    const tableName = options.tableName ?? "memory_items";
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(tableName)) {
      throw new Error(
        `Invalid table name "${tableName}": must contain only letters, numbers, and underscores`
      );
    }
    this.tableName = tableName;
    this.db = new Database(databasePath);
    try {
      this.db.pragma("journal_mode = WAL");
      this.init();
    } catch (err) {
      // Release the open file handle (and WAL/SHM resources) deterministically
      // if initialization throws, since the caller never receives an instance
      // and so can never call close(). The error still propagates unchanged.
      this.db.close();
      throw err;
    }
  }

  private init() {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS ${this.tableName} (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        salience REAL,
        ttl_seconds INTEGER,
        metadata_json TEXT,
        last_accessed_at TEXT,
        is_summary INTEGER,
        embedding_json TEXT,
        links_json TEXT
      );
    `);
    this.migrate();
    // Index for salience-sorted queries
    this.db.exec(`
      CREATE INDEX IF NOT EXISTS idx_${this.tableName}_salience
        ON ${this.tableName} (salience DESC);
    `);
  }

  private migrate() {
    const rows = this.db
      .prepare(`PRAGMA table_info(${this.tableName})`)
      .all() as Array<{ name: string }>;
    const columns = new Set(rows.map(row => row.name));
    const additions: Array<[string, string]> = [
      ["last_accessed_at", "TEXT"],
      ["is_summary", "INTEGER"],
      ["embedding_json", "TEXT"],
      ["links_json", "TEXT"],
    ];
    for (const [column, type] of additions) {
      if (!columns.has(column)) {
        this.db.exec(
          `ALTER TABLE ${this.tableName} ADD COLUMN ${column} ${type}`
        );
      }
    }
  }

  private assertOpen(): void {
    if (this.closed) {
      throw new Error("SqliteStore is closed");
    }
  }

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    this.assertOpen();
    const list = Array.isArray(item) ? item : [item];
    const normalized = list.map(entry => normalizeMemoryItem(entry));
    const stmt = this.db.prepare(
      `INSERT INTO ${this.tableName}
       (id, content, created_at, updated_at, salience, ttl_seconds, metadata_json,
        last_accessed_at, is_summary, embedding_json, links_json)
       VALUES (@id, @content, @created_at, @updated_at, @salience, @ttl_seconds,
        @metadata_json, @last_accessed_at, @is_summary, @embedding_json, @links_json)
       ON CONFLICT(id) DO UPDATE SET
         content=excluded.content,
         updated_at=excluded.updated_at,
         salience=excluded.salience,
         ttl_seconds=excluded.ttl_seconds,
         metadata_json=excluded.metadata_json,
         last_accessed_at=excluded.last_accessed_at,
         is_summary=excluded.is_summary,
         embedding_json=excluded.embedding_json,
         links_json=excluded.links_json`
    );

    const tx = this.db.transaction((entries: MemoryItem[]) => {
      for (const entry of entries) {
        stmt.run({
          id: entry.id,
          content: entry.content,
          created_at: entry.createdAt,
          updated_at: entry.updatedAt ?? entry.createdAt,
          salience: entry.salience ?? 1,
          ttl_seconds: entry.ttlSeconds ?? null,
          metadata_json: JSON.stringify(entry.metadata ?? {}),
          last_accessed_at: entry.lastAccessedAt ?? null,
          is_summary:
            entry.isSummary === undefined ? null : entry.isSummary ? 1 : 0,
          embedding_json:
            entry.embedding === undefined
              ? null
              : JSON.stringify(entry.embedding),
          links_json:
            entry.links === undefined ? null : JSON.stringify(entry.links),
        });
      }
    });

    tx(normalized);
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    this.assertOpen();
    const stmt = this.db.prepare(
      `SELECT * FROM ${this.tableName} WHERE id = ? LIMIT 1`
    );
    const row = stmt.get(id) as SqliteRow | undefined;
    if (!row) return null;
    return rowToItem(row);
  }

  async query(query: MemoryQuery = {}): Promise<MemoryItem[]> {
    this.assertOpen();
    // Fetch all rows, let applyQueryFilter handle filtering uniformly.
    // This ensures consistent behavior with other store implementations
    // (same `now` for TTL, same case-insensitive text matching, same
    // salience decay logic) and avoids double-filtering bugs.
    const stmt = this.db.prepare(`SELECT * FROM ${this.tableName}`);
    const rows = stmt.all() as SqliteRow[];

    const items: MemoryItem[] = rows.map(rowToItem);
    return applyQueryFilter(items, query);
  }

  async forget(id: string): Promise<boolean> {
    this.assertOpen();
    const stmt = this.db.prepare(`DELETE FROM ${this.tableName} WHERE id = ?`);
    const result = stmt.run(id);
    return result.changes > 0;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.db.close();
  }
}
