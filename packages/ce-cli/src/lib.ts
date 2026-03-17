import { promises as fs, existsSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";
import _Ajv from "ajv";
// Ajv is a CJS package that assigns the class to module.exports directly.
// Under Node16 module resolution, the default import is the namespace object,
// so we extract the constructor from .default to satisfy both runtime and types.
const Ajv = _Ajv as unknown as typeof _Ajv.default;
import {
  pack,
  tracePack,
  diff,
  estimateTokens,
  placeItems,
  analyzeContext,
  effectiveBudget,
  packWithCacheTopology,
  createHandoff,
  pickupHandoff,
  getReadyIssues,
  readBeadsJSONL,
  estimateCost,
  projectCosts,
  createWebhookReporter,
} from "@context-engineering/core";
import type { WebhookReporter } from "@context-engineering/core";
import type {
  ContextItem,
  ContextPack,
  PackDiff,
  TokenEstimator,
  PlacementStrategy,
  ContextQuality,
  HandoffResult,
  PickupResult,
  CostEstimate,
  CostProjection,
} from "@context-engineering/core";
import {
  openaiTokenEstimator,
  anthropicTokenEstimator,
} from "@context-engineering/providers";

export type SchemaName =
  | "context-item"
  | "context-plan"
  | "context-pack"
  | "context-trace"
  | "memory-item"
  | "cache-aware-pack"
  | "cost-estimate"
  | "beads-issue"
  | "pipeline-result"
  | "webhook-analytics";

const schemaFileMap: Record<SchemaName, string> = {
  "context-item": "context-item.schema.json",
  "context-plan": "context-plan.schema.json",
  "context-pack": "context-pack.schema.json",
  "context-trace": "context-trace.schema.json",
  "memory-item": "memory-item.schema.json",
  "cache-aware-pack": "cache-aware-pack.schema.json",
  "cost-estimate": "cost-estimate.schema.json",
  "beads-issue": "beads-issue.schema.json",
  "pipeline-result": "pipeline-result.schema.json",
  "webhook-analytics": "webhook-analytics.schema.json",
};

export async function loadItemsFromFile(
  filePath: string
): Promise<ContextItem[]> {
  const raw = await fs.readFile(filePath, "utf-8");
  const trimmed = raw.trim();

  if (!trimmed) return [];

  if (filePath.endsWith(".jsonl")) {
    return trimmed
      .split(/\r?\n/)
      .filter(Boolean)
      .map(line => JSON.parse(line));
  }

  const parsed = JSON.parse(trimmed);
  if (Array.isArray(parsed)) return parsed;
  if (parsed && Array.isArray(parsed.items)) return parsed.items;
  if (parsed && Array.isArray(parsed.selected))
    return [...parsed.selected, ...(parsed.dropped ?? [])];
  throw new Error(
    "Invalid items file: expected array, { items: [] }, or a ContextPack ({ selected: [] })"
  );
}

export function resolveTokenEstimator(
  provider?: string
): TokenEstimator | undefined {
  if (provider === "openai") return openaiTokenEstimator;
  if (provider === "anthropic") return anthropicTokenEstimator;
  return undefined;
}

export function runPack(
  items: ContextItem[],
  budget: number,
  options: { provider?: string } = {}
): ContextPack {
  return pack(
    items,
    { maxTokens: budget },
    { tokenEstimator: resolveTokenEstimator(options.provider) }
  );
}

export function runTrace(
  items: ContextItem[],
  budget: number,
  options: { provider?: string } = {}
) {
  return tracePack(
    items,
    { maxTokens: budget },
    { tokenEstimator: resolveTokenEstimator(options.provider) }
  );
}

export function runDiff(
  before: ContextPack | ContextItem[],
  after: ContextPack | ContextItem[]
): PackDiff {
  return diff(before, after);
}

export function runBudget(
  text: string,
  options: { provider?: string } = {}
): number {
  return estimateTokens(text, {
    estimator: resolveTokenEstimator(options.provider),
  });
}

/**
 * Walk up from startDir looking for a "schemas" directory.
 * Stops at the filesystem root.
 */
function findSchemasDir(startDir: string): string | null {
  let current = startDir;
  // Walk to the root -- path.dirname(root) === root stops the loop
  while (true) {
    const candidate = path.join(current, "schemas");
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return null;
}

// Schema cache: loaded once per process, reused across lintFile calls.
let cachedSchemas: Record<string, unknown> | null = null;
let cachedAjv: InstanceType<typeof _Ajv.default> | null = null;

export async function loadSchemas(): Promise<Record<string, unknown>> {
  if (cachedSchemas) return cachedSchemas;

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
  cachedSchemas = schemas;
  return schemas;
}

function getAjv(
  schemas: Record<string, unknown>
): InstanceType<typeof _Ajv.default> {
  if (cachedAjv) return cachedAjv;

  const ajv = new Ajv({
    allErrors: true,
    strict: false,
    validateSchema: false,
  });

  Object.values(schemas).forEach(schema => {
    ajv.addSchema(schema as Record<string, unknown>);
  });

  cachedAjv = ajv;
  return ajv;
}

export async function lintFile(schemaName: SchemaName, data: unknown) {
  const schemas = await loadSchemas();
  const ajv = getAjv(schemas);

  const schema = schemas[schemaName];
  if (!schema) throw new Error(`Unknown schema: ${schemaName}`);
  const validate = ajv.compile(schema as Record<string, unknown>);

  // If data is an array and schema expects an object, validate each element
  if (Array.isArray(data)) {
    const schemaType = (schema as Record<string, unknown>).type;
    if (schemaType === "object" || !schemaType) {
      const allErrors: Array<{ index: number; errors: unknown[] }> = [];
      for (let i = 0; i < data.length; i++) {
        const valid = validate(data[i]);
        if (!valid) {
          allErrors.push({
            index: i,
            errors: (validate.errors ?? []).map(e => ({
              ...e,
              instancePath: `[${i}]${e.instancePath ?? ""}`,
            })),
          });
        }
      }
      if (allErrors.length === 0) {
        return { valid: true, errors: [], itemCount: data.length };
      }
      return {
        valid: false,
        errors: allErrors.flatMap(e => e.errors),
        itemCount: data.length,
      };
    }
  }

  const valid = validate(data);
  return { valid, errors: validate.errors ?? [] };
}

// ─── Place ────────────────────────────────────────────────────────────

export function runPlace(
  items: ContextItem[],
  budget: number,
  options: {
    strategy?: PlacementStrategy;
    model?: string;
    provider?: string;
  } = {}
): { selected: ContextItem[]; totalTokens: number; strategy: string } {
  const packed = pack(
    items,
    { maxTokens: budget },
    {
      tokenEstimator: resolveTokenEstimator(options.provider),
    }
  );
  const placed = placeItems(packed.selected, {
    strategy: options.strategy ?? "attention-optimized",
    model: options.model,
  });
  return {
    selected: placed,
    totalTokens: packed.totalTokens,
    strategy: options.strategy ?? "attention-optimized",
  };
}

// ─── Quality ──────────────────────────────────────────────────────────

export function runQuality(
  items: ContextItem[],
  budget: number,
  options: { provider?: string } = {}
): ContextQuality {
  const packed = pack(
    items,
    { maxTokens: budget },
    {
      tokenEstimator: resolveTokenEstimator(options.provider),
    }
  );
  return analyzeContext(packed.selected);
}

// ─── Effective Budget ─────────────────────────────────────────────────

export function runEffectiveBudget(
  advertisedTokens: number,
  model?: string
): { advertised: number; effective: number; model: string; ratio: number } {
  const effective = effectiveBudget(advertisedTokens, model);
  const m = model ?? "default";
  return {
    advertised: advertisedTokens,
    effective,
    model: m,
    ratio: Math.round((effective / advertisedTokens) * 100) / 100,
  };
}

// ─── Handoff ──────────────────────────────────────────────────────────

export function runHandoff(
  items: ContextItem[],
  budget: number,
  options: {
    provider?: string;
    cacheTopology?: boolean;
    includeDropped?: boolean;
    agent?: string;
    sessionId?: string;
    notes?: string;
  } = {}
): HandoffResult {
  let packed: ContextPack;

  if (options.cacheTopology) {
    packed = packWithCacheTopology(
      items,
      { maxTokens: budget },
      {
        tokenEstimator: resolveTokenEstimator(options.provider),
      }
    );
  } else {
    packed = pack(
      items,
      { maxTokens: budget },
      {
        tokenEstimator: resolveTokenEstimator(options.provider),
      }
    );
  }

  return createHandoff(packed, {
    includeDropped: options.includeDropped,
    agent: options.agent,
    sessionId: options.sessionId,
    handoffNotes: options.notes,
  });
}

// ─── Pickup ───────────────────────────────────────────────────────────

export function runPickup(
  jsonl: string,
  options: { ready?: boolean } = {}
): PickupResult {
  const result = pickupHandoff(jsonl);

  if (options.ready) {
    const allIssues = readBeadsJSONL(jsonl);
    const ready = getReadyIssues(allIssues);
    // BEADS IDs use "ce-" prefix (contextItemToBeads creates "ce-{id}"),
    // and beadsToContextItem strips it back, so recovered item.id matches
    // the original. We reconstruct the BEADS ID here for the comparison.
    return {
      ...result,
      items: result.items.filter(item =>
        ready.some(issue => issue.id === `ce-${item.id}`)
      ),
    };
  }

  return result;
}

// ─── Cost ─────────────────────────────────────────────────────────────

export function runCost(
  items: ContextItem[],
  budget: number,
  model: string,
  options: {
    provider?: string;
    outputTokens?: number;
    requestCount?: number;
    requestsPerDay?: number;
  } = {}
): { estimate: CostEstimate; projection?: CostProjection } {
  const packed = packWithCacheTopology(
    items,
    { maxTokens: budget },
    {
      tokenEstimator: resolveTokenEstimator(options.provider),
    }
  );

  const estimate = estimateCost(packed, model, options.outputTokens);

  let projection: CostProjection | undefined;
  if (options.requestCount) {
    projection = projectCosts(packed, model, options.requestCount, {
      outputTokens: options.outputTokens,
      requestsPerDay: options.requestsPerDay,
    });
  }

  return { estimate, projection };
}

// ─── Webhook Reporter ────────────────────────────────────────────────

export function createReporterFromCliOptions(options: {
  webhookUrl?: string;
  webhookHandoffUrl?: string;
  webhookQualityUrl?: string;
  webhookCostUrl?: string;
  model?: string;
}): WebhookReporter {
  return createWebhookReporter({
    analyticsUrl: options.webhookUrl,
    handoffUrl: options.webhookHandoffUrl,
    qualityUrl: options.webhookQualityUrl,
    costUrl: options.webhookCostUrl,
    model: options.model,
  });
}
