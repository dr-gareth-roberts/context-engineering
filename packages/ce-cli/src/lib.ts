import { promises as fs, existsSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import Ajv from "ajv";
import { pack, tracePack, diff, estimateTokens } from "@ce/core";
import type { ContextItem, ContextPack, PackDiff, TokenEstimator } from "@ce/core";
import { openaiTokenEstimator, anthropicTokenEstimator } from "@ce/providers";

export type SchemaName =
  | "context-item"
  | "context-plan"
  | "context-pack"
  | "context-trace"
  | "memory-item";

const schemaFileMap: Record<SchemaName, string> = {
  "context-item": "context-item.schema.json",
  "context-plan": "context-plan.schema.json",
  "context-pack": "context-pack.schema.json",
  "context-trace": "context-trace.schema.json",
  "memory-item": "memory-item.schema.json"
};

export async function loadItemsFromFile(filePath: string): Promise<ContextItem[]> {
  const raw = await fs.readFile(filePath, "utf-8");
  const trimmed = raw.trim();

  if (!trimmed) return [];

  if (filePath.endsWith(".jsonl")) {
    return trimmed
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  }

  const parsed = JSON.parse(trimmed);
  if (Array.isArray(parsed)) return parsed;
  if (parsed && Array.isArray(parsed.items)) return parsed.items;
  throw new Error("Invalid items file: expected array or { items: [] }");
}

export function resolveTokenEstimator(provider?: string): TokenEstimator | undefined {
  if (provider === "openai") return openaiTokenEstimator;
  if (provider === "anthropic") return anthropicTokenEstimator;
  return undefined;
}

export function runPack(
  items: ContextItem[],
  budget: number,
  options: { provider?: string } = {}
): ContextPack {
  return pack(items, { maxTokens: budget }, { tokenEstimator: resolveTokenEstimator(options.provider) });
}

export function runTrace(
  items: ContextItem[],
  budget: number,
  options: { provider?: string } = {}
) {
  return tracePack(items, { maxTokens: budget }, { tokenEstimator: resolveTokenEstimator(options.provider) });
}

export function runDiff(
  before: ContextPack | ContextItem[],
  after: ContextPack | ContextItem[]
): PackDiff {
  return diff(before, after);
}

export function runBudget(text: string, options: { provider?: string } = {}): number {
  return estimateTokens(text, { estimator: resolveTokenEstimator(options.provider) });
}

function findSchemasDir(startDir: string): string | null {
  let current = startDir;
  for (let i = 0; i < 8; i += 1) {
    const candidate = path.join(current, "schemas");
    if (fsExistsSync(candidate)) return candidate;
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return null;
}

function fsExistsSync(target: string): boolean {
  try {
    return existsSync(target);
  } catch {
    return false;
  }
}

export async function loadSchemas(): Promise<Record<string, unknown>> {
  const cwd = process.cwd();
  const baseDir =
    findSchemasDir(cwd) ??
    findSchemasDir(path.dirname(fileURLToPath(import.meta.url)));
  if (!baseDir) {
    throw new Error("Could not locate schemas directory");
  }

  const schemas: Record<string, unknown> = {};
  await Promise.all(
    Object.entries(schemaFileMap).map(async ([key, filename]) => {
      const schemaPath = path.join(baseDir, filename);
      const content = await fs.readFile(schemaPath, "utf-8");
      schemas[key] = JSON.parse(content);
    })
  );
  return schemas;
}

export async function lintFile(schemaName: SchemaName, data: unknown) {
  const schemas = await loadSchemas();
  const ajv = new Ajv({ allErrors: true, strict: false });

  Object.values(schemas).forEach((schema) => {
    ajv.addSchema(schema as any);
  });

  const schema = schemas[schemaName];
  if (!schema) throw new Error(`Unknown schema: ${schemaName}`);
  const validate = ajv.compile(schema as any);
  const valid = validate(data);
  return { valid, errors: validate.errors ?? [] };
}
