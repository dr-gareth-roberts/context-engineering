import type { MemoryItem } from "@context-engineering/core";

export interface MemoryQuery {
  text?: string;
  limit?: number;
  minSalience?: number;
  includeExpired?: boolean;
  halfLifeSeconds?: number;
  now?: number;
}

export interface MemoryStore {
  put(item: Partial<MemoryItem> | Partial<MemoryItem>[]): Promise<MemoryItem[]>;
  get(id: string): Promise<MemoryItem | null>;
  query(query?: MemoryQuery): Promise<MemoryItem[]>;
  forget(id: string): Promise<boolean>;
  close(): Promise<void>;
}
