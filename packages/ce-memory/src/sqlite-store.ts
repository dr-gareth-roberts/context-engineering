import type { MemoryItem } from "@ce/core";
import Database from "better-sqlite3";
import type { MemoryQuery, MemoryStore } from "./types.js";
import { applyQueryFilter, normalizeMemoryItem } from "./utils.js";

interface SqliteStoreOptions {
  tableName?: string;
}

type DatabaseInstance = ReturnType<typeof Database>;

export class SqliteStore implements MemoryStore {
  private db: DatabaseInstance;
  private tableName: string;

  constructor(databasePath: string, options: SqliteStoreOptions = {}) {
    const tableName = options.tableName ?? "memory_items";
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(tableName)) {
      throw new Error(
        `Invalid table name "${tableName}": must contain only letters, numbers, and underscores`
      );
    }
    this.tableName = tableName;
    this.db = new Database(databasePath);
    this.db.pragma("journal_mode = WAL");
    this.init();
  }

  private init() {
    const createSql = `
      CREATE TABLE IF NOT EXISTS ${this.tableName} (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT,
        salience REAL,
        ttl_seconds INTEGER,
        metadata_json TEXT
      );
    `;
    this.db.exec(createSql);
  }

  async put(
    item: Partial<MemoryItem> | Partial<MemoryItem>[]
  ): Promise<MemoryItem[]> {
    const list = Array.isArray(item) ? item : [item];
    const normalized = list.map(entry => normalizeMemoryItem(entry));
    const stmt = this.db.prepare(
      `INSERT INTO ${this.tableName}
       (id, content, created_at, updated_at, salience, ttl_seconds, metadata_json)
       VALUES (@id, @content, @created_at, @updated_at, @salience, @ttl_seconds, @metadata_json)
       ON CONFLICT(id) DO UPDATE SET
         content=excluded.content,
         updated_at=excluded.updated_at,
         salience=excluded.salience,
         ttl_seconds=excluded.ttl_seconds,
         metadata_json=excluded.metadata_json`
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
        });
      }
    });

    tx(normalized);
    return normalized;
  }

  async get(id: string): Promise<MemoryItem | null> {
    const stmt = this.db.prepare(
      `SELECT * FROM ${this.tableName} WHERE id = ? LIMIT 1`
    );
    const row = stmt.get(id) as
      | {
          id: string;
          content: string;
          created_at: string;
          updated_at: string | null;
          salience: number | null;
          ttl_seconds: number | null;
          metadata_json: string | null;
        }
      | undefined;

    if (!row) return null;

    return {
      id: row.id,
      content: row.content,
      createdAt: row.created_at,
      updatedAt: row.updated_at ?? undefined,
      salience: row.salience ?? undefined,
      ttlSeconds: row.ttl_seconds ?? undefined,
      metadata: row.metadata_json ? JSON.parse(row.metadata_json) : undefined,
    };
  }

  async query(query: MemoryQuery = {}): Promise<MemoryItem[]> {
    const stmt = this.db.prepare(`SELECT * FROM ${this.tableName}`);
    const rows = stmt.all() as Array<{
      id: string;
      content: string;
      created_at: string;
      updated_at: string | null;
      salience: number | null;
      ttl_seconds: number | null;
      metadata_json: string | null;
    }>;

    const items: MemoryItem[] = rows.map(row => ({
      id: row.id,
      content: row.content,
      createdAt: row.created_at,
      updatedAt: row.updated_at ?? undefined,
      salience: row.salience ?? undefined,
      ttlSeconds: row.ttl_seconds ?? undefined,
      metadata: row.metadata_json ? JSON.parse(row.metadata_json) : undefined,
    }));

    return applyQueryFilter(items, query);
  }

  async forget(id: string): Promise<boolean> {
    const stmt = this.db.prepare(`DELETE FROM ${this.tableName} WHERE id = ?`);
    const result = stmt.run(id);
    return result.changes > 0;
  }

  close(): void {
    this.db.close();
  }
}
