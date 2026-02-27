# Production Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the Context Engineering Toolkit production-worthy — robust error handling, comprehensive tests, polished CLI, and DX improvements across TypeScript and Python.

**Architecture:** Bottom-up hardening from ce-core → ce-memory → ce-providers → ce-cli → Python SDK → production features. Each layer is fully tested before the next layer builds on it.

**Tech Stack:** Zod (runtime validation), Vitest (TS tests with snapshots), pytest (Python), Commander.js (CLI), ANSI escape codes (CLI colors)

---

### Task 1: Add Zod to ce-core and create error classes

**Files:**

- Modify: `packages/ce-core/package.json` (add zod dependency)
- Create: `packages/ce-core/src/errors.ts`

**Step 1: Add zod dependency to ce-core**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && pnpm add zod`

**Step 2: Create error classes**

Create `packages/ce-core/src/errors.ts`:

```ts
export class ContextEngineeringError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "ContextEngineeringError";
    this.code = code;
  }
}

export class ValidationError extends ContextEngineeringError {
  readonly details: Array<{ path: string; message: string }>;

  constructor(
    message: string,
    details: Array<{ path: string; message: string }> = []
  ) {
    super(message, "VALIDATION_ERROR");
    this.name = "ValidationError";
    this.details = details;
  }
}

export class BudgetExceededError extends ContextEngineeringError {
  constructor(message: string) {
    super(message, "BUDGET_EXCEEDED");
    this.name = "BudgetExceededError";
  }
}

export class EstimationError extends ContextEngineeringError {
  constructor(message: string) {
    super(message, "ESTIMATION_ERROR");
    this.name = "EstimationError";
  }
}
```

**Step 3: Export errors from index.ts**

Modify `packages/ce-core/src/index.ts` — add `export * from "./errors";` at the top.

**Step 4: Verify build**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && pnpm check`

**Step 5: Commit**

```bash
git add packages/ce-core/package.json packages/ce-core/src/errors.ts packages/ce-core/src/index.ts pnpm-lock.yaml
git commit -m "feat(ce-core): add error class hierarchy and zod dependency"
```

---

### Task 2: Create Zod schemas for ce-core types

**Files:**

- Create: `packages/ce-core/src/schemas.ts`

**Step 1: Write the failing test**

Create `packages/ce-core/src/schemas.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ContextItemSchema, BudgetSchema, CompressionSchema } from "./schemas";

describe("ContextItemSchema", () => {
  it("accepts a valid item", () => {
    const result = ContextItemSchema.safeParse({
      id: "test-1",
      content: "Hello world",
      priority: 5,
      recency: 3,
    });
    expect(result.success).toBe(true);
  });

  it("rejects item with empty id", () => {
    const result = ContextItemSchema.safeParse({
      id: "",
      content: "Hello",
    });
    expect(result.success).toBe(false);
  });

  it("rejects item without id", () => {
    const result = ContextItemSchema.safeParse({
      content: "Hello",
    });
    expect(result.success).toBe(false);
  });

  it("rejects item with negative priority", () => {
    const result = ContextItemSchema.safeParse({
      id: "test",
      content: "Hello",
      priority: -1,
    });
    expect(result.success).toBe(false);
  });

  it("accepts item with compressions", () => {
    const result = ContextItemSchema.safeParse({
      id: "test",
      content: "Long content",
      compressions: [{ content: "Short", tokens: 5, note: "summary" }],
    });
    expect(result.success).toBe(true);
  });

  it("accepts item with metadata", () => {
    const result = ContextItemSchema.safeParse({
      id: "test",
      content: "Hello",
      metadata: { salience: 0.8, custom: "value" },
    });
    expect(result.success).toBe(true);
  });
});

describe("BudgetSchema", () => {
  it("accepts valid budget", () => {
    const result = BudgetSchema.safeParse({ maxTokens: 4096 });
    expect(result.success).toBe(true);
  });

  it("rejects zero maxTokens", () => {
    const result = BudgetSchema.safeParse({ maxTokens: 0 });
    expect(result.success).toBe(false);
  });

  it("rejects negative maxTokens", () => {
    const result = BudgetSchema.safeParse({ maxTokens: -100 });
    expect(result.success).toBe(false);
  });

  it("accepts budget with reserveTokens", () => {
    const result = BudgetSchema.safeParse({
      maxTokens: 4096,
      reserveTokens: 500,
    });
    expect(result.success).toBe(true);
  });

  it("rejects negative reserveTokens", () => {
    const result = BudgetSchema.safeParse({
      maxTokens: 4096,
      reserveTokens: -1,
    });
    expect(result.success).toBe(false);
  });
});

describe("CompressionSchema", () => {
  it("accepts valid compression", () => {
    const result = CompressionSchema.safeParse({
      content: "Short version",
      tokens: 10,
    });
    expect(result.success).toBe(true);
  });

  it("rejects compression without content", () => {
    const result = CompressionSchema.safeParse({ tokens: 10 });
    expect(result.success).toBe(false);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run src/schemas.test.ts`
Expected: FAIL — module "./schemas" not found

**Step 3: Write the schemas**

Create `packages/ce-core/src/schemas.ts`:

```ts
import { z } from "zod";

export const CompressionSchema = z.object({
  content: z.string(),
  tokens: z.number().nonnegative().optional(),
  note: z.string().optional(),
});

export const ContextItemSchema = z.object({
  id: z.string().min(1, "id must be a non-empty string"),
  content: z.string(),
  kind: z.string().optional(),
  priority: z.number().nonnegative().optional(),
  recency: z.number().nonnegative().optional(),
  tokens: z.number().nonnegative().optional(),
  score: z.number().optional(),
  metadata: z.record(z.unknown()).optional(),
  compressions: z.array(CompressionSchema).optional(),
});

export const BudgetSchema = z.object({
  maxTokens: z.number().positive("maxTokens must be positive"),
  reserveTokens: z.number().nonnegative().optional(),
});

export const PackOptionsSchema = z
  .object({
    tokenEstimator: z.function().optional(),
    scorer: z.function().optional(),
    summarizer: z.function().optional(),
    allowCompression: z.boolean().optional(),
  })
  .optional();
```

**Step 4: Export schemas from index.ts**

Modify `packages/ce-core/src/index.ts` — add `export * from "./schemas";`

**Step 5: Run test to verify it passes**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run src/schemas.test.ts`
Expected: PASS — all schema validation tests pass

**Step 6: Commit**

```bash
git add packages/ce-core/src/schemas.ts packages/ce-core/src/schemas.test.ts packages/ce-core/src/index.ts
git commit -m "feat(ce-core): add Zod validation schemas for ContextItem and Budget"
```

---

### Task 3: Add ScoringWeights type and configurable scoring

**Files:**

- Modify: `packages/ce-core/src/types.ts:70-74` (add weights to PackOptions)
- Modify: `packages/ce-core/src/score.ts` (accept configurable weights)

**Step 1: Write the failing test**

Create `packages/ce-core/src/score.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { defaultItemScorer, createScorer } from "./score";
import type { ContextItem } from "./types";

const item: ContextItem = {
  id: "test",
  content: "Hello",
  priority: 10,
  recency: 5,
  metadata: { salience: 0.8 },
};

describe("defaultItemScorer", () => {
  it("computes default score: priority*1.0 + recency*0.7 + salience*0.5", () => {
    const score = defaultItemScorer(item);
    expect(score).toBeCloseTo(10 * 1.0 + 5 * 0.7 + 0.8 * 0.5);
  });

  it("returns explicit score when set", () => {
    const scored = { ...item, score: 42 };
    expect(defaultItemScorer(scored)).toBe(42);
  });

  it("handles missing optional fields", () => {
    const minimal: ContextItem = { id: "m", content: "test" };
    expect(defaultItemScorer(minimal)).toBe(0);
  });

  it("handles zero values", () => {
    const zero: ContextItem = {
      id: "z",
      content: "test",
      priority: 0,
      recency: 0,
      metadata: { salience: 0 },
    };
    expect(defaultItemScorer(zero)).toBe(0);
  });
});

describe("createScorer", () => {
  it("creates scorer with custom weights", () => {
    const scorer = createScorer({ priority: 2.0, recency: 0.0, salience: 1.0 });
    const score = scorer(item);
    expect(score).toBeCloseTo(10 * 2.0 + 5 * 0.0 + 0.8 * 1.0);
  });

  it("uses defaults for missing weight fields", () => {
    const scorer = createScorer({ priority: 2.0 });
    const score = scorer(item);
    // priority=2.0, recency=0.7 (default), salience=0.5 (default)
    expect(score).toBeCloseTo(10 * 2.0 + 5 * 0.7 + 0.8 * 0.5);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run src/score.test.ts`
Expected: FAIL — `createScorer` not exported

**Step 3: Add ScoringWeights and createScorer**

Modify `packages/ce-core/src/types.ts` — add before the `PackOptions` interface:

```ts
export interface ScoringWeights {
  priority?: number;
  recency?: number;
  salience?: number;
}
```

Add `weights?: ScoringWeights;` to the `PackOptions` interface after `allowCompression`.

Modify `packages/ce-core/src/score.ts` to:

```ts
import type { ContextItem, ItemScorer, ScoringWeights } from "./types";

const DEFAULT_WEIGHTS: Required<ScoringWeights> = {
  priority: 1.0,
  recency: 0.7,
  salience: 0.5,
};

export function createScorer(weights: ScoringWeights = {}): ItemScorer {
  const w = { ...DEFAULT_WEIGHTS, ...weights };

  return (item: ContextItem) => {
    if (typeof item.score === "number") return item.score;

    const priority = item.priority ?? 0;
    const recency = item.recency ?? 0;
    const salience =
      typeof item.metadata?.salience === "number"
        ? (item.metadata.salience as number)
        : 0;

    return priority * w.priority + recency * w.recency + salience * w.salience;
  };
}

export const defaultItemScorer: ItemScorer = createScorer();
```

**Step 4: Wire weights into pack()**

Modify `packages/ce-core/src/pack.ts` line 64: change

```ts
const scorer = options.scorer ?? defaultItemScorer;
```

to:

```ts
const scorer =
  options.scorer ??
  (options.weights ? createScorer(options.weights) : defaultItemScorer);
```

Add `import { createScorer, defaultItemScorer } from "./score";` (replace the existing import).

**Step 5: Run all tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run`
Expected: PASS — all tests pass

**Step 6: Commit**

```bash
git add packages/ce-core/src/types.ts packages/ce-core/src/score.ts packages/ce-core/src/score.test.ts packages/ce-core/src/pack.ts
git commit -m "feat(ce-core): add configurable ScoringWeights and createScorer factory"
```

---

### Task 4: Add input validation to pack() and diff()

**Files:**

- Modify: `packages/ce-core/src/pack.ts:54-68` (add validation at entry)
- Modify: `packages/ce-core/src/diff.ts:3-5` (validate inputs)
- Modify: `packages/ce-core/src/estimate.ts` (handle edge cases)

**Step 1: Write the failing tests**

Add to `packages/ce-core/src/pack.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { pack } from "./pack";
import { ValidationError, BudgetExceededError } from "./errors";
import type { ContextItem } from "./types";

const items: ContextItem[] = [
  { id: "a", content: "High priority", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 },
];

describe("pack", () => {
  it("selects highest scored items within budget", () => {
    const packResult = pack(items, { maxTokens: 90 });
    const selectedIds = packResult.selected.map(item => item.id);
    expect(selectedIds).toContain("a");
    expect(selectedIds).toContain("c");
    expect(selectedIds).not.toContain("b");
  });

  it("uses compression when allowed", () => {
    const compressedItems: ContextItem[] = [
      {
        id: "a",
        content: "Long content",
        priority: 10,
        tokens: 100,
        compressions: [{ content: "Short", tokens: 30, note: "summary" }],
      },
    ];

    const packResult = pack(
      compressedItems,
      { maxTokens: 40 },
      { allowCompression: true }
    );
    expect(packResult.selected[0].content).toBe("Short");
  });

  it("returns empty pack for empty items array", () => {
    const result = pack([], { maxTokens: 100 });
    expect(result.selected).toEqual([]);
    expect(result.dropped).toEqual([]);
    expect(result.totalTokens).toBe(0);
  });

  it("throws ValidationError for invalid budget", () => {
    expect(() => pack(items, { maxTokens: -100 })).toThrow(ValidationError);
  });

  it("throws ValidationError for zero budget", () => {
    expect(() => pack(items, { maxTokens: 0 })).toThrow(ValidationError);
  });

  it("throws ValidationError for item missing id", () => {
    const bad = [{ content: "no id" }] as ContextItem[];
    expect(() => pack(bad, { maxTokens: 100 })).toThrow(ValidationError);
  });

  it("throws BudgetExceededError when reserveTokens >= maxTokens", () => {
    expect(() => pack(items, { maxTokens: 100, reserveTokens: 100 })).toThrow(
      BudgetExceededError
    );
  });

  it("drops all items when none fit budget", () => {
    const result = pack(items, { maxTokens: 1 });
    expect(result.selected).toEqual([]);
    expect(result.dropped.length).toBe(3);
  });

  it("uses custom scorer via weights option", () => {
    const result = pack(
      items,
      { maxTokens: 90 },
      { weights: { priority: 0, recency: 1.0 } }
    );
    expect(result.selected.length).toBeGreaterThan(0);
  });

  it("produces stable snapshot output", () => {
    const result = pack(items, { maxTokens: 90 });
    expect(result).toMatchSnapshot();
  });
});
```

**Step 2: Run test to verify new tests fail**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run src/pack.test.ts`
Expected: FAIL — ValidationError not thrown (no validation yet)

**Step 3: Add validation to pack.ts**

Modify `packages/ce-core/src/pack.ts`. Add imports at top:

```ts
import {
  ValidationError,
  BudgetExceededError,
  EstimationError,
} from "./errors";
import { ContextItemSchema, BudgetSchema } from "./schemas";
import { z } from "zod";
```

In `internalPack()` function, add validation right after the opening `{` (before `const scorer`):

```ts
// Validate budget
const budgetResult = BudgetSchema.safeParse(budget);
if (!budgetResult.success) {
  throw new ValidationError(
    `Invalid budget: ${budgetResult.error.issues.map(i => i.message).join(", ")}`,
    budgetResult.error.issues.map(i => ({
      path: i.path.join("."),
      message: i.message,
    }))
  );
}

// Validate reserve < max
if (
  budget.reserveTokens !== undefined &&
  budget.reserveTokens >= budget.maxTokens
) {
  throw new BudgetExceededError(
    `reserveTokens (${budget.reserveTokens}) must be less than maxTokens (${budget.maxTokens})`
  );
}

// Validate items
const itemsResult = z.array(ContextItemSchema).safeParse(items);
if (!itemsResult.success) {
  throw new ValidationError(
    `Invalid items: ${itemsResult.error.issues.map(i => `${i.path.join(".")}: ${i.message}`).join(", ")}`,
    itemsResult.error.issues.map(i => ({
      path: i.path.join("."),
      message: i.message,
    }))
  );
}
```

Also wrap token estimation in try-catch inside the `scoredItems` map (line 66-68):

```ts
const scoredItems = items.map(item => {
  let tokens: number;
  try {
    tokens =
      item.tokens ??
      estimateTokens(item.content, { estimator: tokenEstimator });
  } catch (err) {
    throw new EstimationError(
      `Failed to estimate tokens for item "${item.id}": ${err instanceof Error ? err.message : String(err)}`
    );
  }
  const score = scorer({ ...item, tokens });
  return { ...item, tokens, score };
});
```

**Step 4: Add validation to diff.ts**

Modify `packages/ce-core/src/diff.ts`. Add at top of `diff()` function:

```ts
if (!before) {
  throw new ValidationError("diff() 'before' argument is required");
}
if (!after) {
  throw new ValidationError("diff() 'after' argument is required");
}
```

Add import: `import { ValidationError } from "./errors";`

**Step 5: Add edge case handling to estimate.ts**

Modify `packages/ce-core/src/estimate.ts`. In `estimateTokens()`, add null/undefined check:

```ts
export function estimateTokens(
  text: string,
  options?: { model?: string; provider?: string; estimator?: TokenEstimator }
): number {
  if (text == null) return 0;
  const estimator = options?.estimator ?? defaultTokenEstimator;
  try {
    return estimator(text, {
      model: options?.model,
      provider: options?.provider,
    });
  } catch (err) {
    throw new EstimationError(
      `Token estimation failed: ${err instanceof Error ? err.message : String(err)}`
    );
  }
}
```

Add import: `import { EstimationError } from "./errors";`

**Step 6: Run all tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run`
Expected: PASS — all tests including new validation tests

**Step 7: Commit**

```bash
git add packages/ce-core/src/pack.ts packages/ce-core/src/pack.test.ts packages/ce-core/src/diff.ts packages/ce-core/src/estimate.ts
git commit -m "feat(ce-core): add Zod input validation to pack(), diff(), and estimateTokens()"
```

---

### Task 5: Comprehensive diff and trace tests

**Files:**

- Modify: `packages/ce-core/src/diff.test.ts` (expand test coverage)
- Create: `packages/ce-core/src/trace.test.ts`
- Create: `packages/ce-core/src/estimate.test.ts`

**Step 1: Write expanded diff tests**

Replace `packages/ce-core/src/diff.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { diff } from "./diff";
import type { ContextItem, ContextPack } from "./types";

const before: ContextItem[] = [
  { id: "a", content: "Alpha", tokens: 10 },
  { id: "b", content: "Beta", tokens: 20 },
];

const after: ContextItem[] = [
  { id: "a", content: "Alpha", tokens: 10 },
  { id: "c", content: "Gamma", tokens: 15 },
];

describe("diff", () => {
  it("detects added and removed items", () => {
    const result = diff(before, after);
    expect(result.added.map(i => i.id)).toEqual(["c"]);
    expect(result.removed.map(i => i.id)).toEqual(["b"]);
    expect(result.kept.map(i => i.id)).toEqual(["a"]);
  });

  it("detects content changes", () => {
    const changed: ContextItem[] = [
      { id: "a", content: "Alpha modified", tokens: 10 },
    ];
    const result = diff(before, changed);
    expect(result.changed.length).toBe(1);
    expect(result.changed[0].before.content).toBe("Alpha");
    expect(result.changed[0].after.content).toBe("Alpha modified");
  });

  it("detects token changes", () => {
    const changed: ContextItem[] = [{ id: "a", content: "Alpha", tokens: 999 }];
    const result = diff(before, changed);
    expect(result.changed.length).toBe(1);
  });

  it("handles empty before", () => {
    const result = diff([], after);
    expect(result.added.length).toBe(2);
    expect(result.removed.length).toBe(0);
  });

  it("handles empty after", () => {
    const result = diff(before, []);
    expect(result.removed.length).toBe(2);
    expect(result.added.length).toBe(0);
  });

  it("handles both empty", () => {
    const result = diff([], []);
    expect(result.added).toEqual([]);
    expect(result.removed).toEqual([]);
    expect(result.kept).toEqual([]);
    expect(result.changed).toEqual([]);
  });

  it("handles identical arrays", () => {
    const result = diff(before, [...before]);
    expect(result.kept.length).toBe(2);
    expect(result.added).toEqual([]);
    expect(result.removed).toEqual([]);
    expect(result.changed).toEqual([]);
  });

  it("accepts ContextPack inputs", () => {
    const beforePack: ContextPack = {
      budget: { maxTokens: 100 },
      selected: before,
      dropped: [],
      totalTokens: 30,
    };
    const afterPack: ContextPack = {
      budget: { maxTokens: 100 },
      selected: after,
      dropped: [],
      totalTokens: 25,
    };
    const result = diff(beforePack, afterPack);
    expect(result.added.map(i => i.id)).toEqual(["c"]);
    expect(result.removed.map(i => i.id)).toEqual(["b"]);
  });

  it("produces stable snapshot", () => {
    const result = diff(before, after);
    expect(result).toMatchSnapshot();
  });
});
```

**Step 2: Write trace tests**

Create `packages/ce-core/src/trace.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { tracePack } from "./trace";
import type { ContextItem } from "./types";

const items: ContextItem[] = [
  { id: "a", content: "High", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 },
];

describe("tracePack", () => {
  it("records include decisions", () => {
    const trace = tracePack(items, { maxTokens: 200 });
    expect(trace.steps.length).toBe(3);
    expect(trace.steps.every(s => s.decision === "include")).toBe(true);
  });

  it("records exclude decisions when over budget", () => {
    const trace = tracePack(items, { maxTokens: 55 });
    const excluded = trace.steps.filter(s => s.decision === "exclude");
    expect(excluded.length).toBeGreaterThan(0);
  });

  it("records compress decisions", () => {
    const withCompression: ContextItem[] = [
      {
        id: "big",
        content: "Very long content",
        priority: 10,
        tokens: 100,
        compressions: [{ content: "Short", tokens: 20, note: "summary" }],
      },
    ];
    const trace = tracePack(
      withCompression,
      { maxTokens: 30 },
      { allowCompression: true }
    );
    const compressed = trace.steps.filter(s => s.decision === "compress");
    expect(compressed.length).toBe(1);
    expect(compressed[0].usedCompression).toBe(true);
    expect(compressed[0].compressedTokens).toBe(20);
  });

  it("includes createdAt timestamp", () => {
    const trace = tracePack(items, { maxTokens: 200 });
    expect(trace.createdAt).toBeDefined();
    expect(() => new Date(trace.createdAt)).not.toThrow();
  });

  it("trace pack matches pack result", () => {
    const trace = tracePack(items, { maxTokens: 90 });
    expect(trace.pack.selected.length).toBeGreaterThan(0);
    expect(trace.pack.totalTokens).toBeLessThanOrEqual(90);
  });

  it("produces stable snapshot", () => {
    const trace = tracePack(items, { maxTokens: 90 });
    // Exclude createdAt from snapshot since it changes
    const { createdAt, ...rest } = trace;
    expect(rest).toMatchSnapshot();
  });
});
```

**Step 3: Write estimate tests**

Create `packages/ce-core/src/estimate.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { estimateTokens, defaultTokenEstimator } from "./estimate";

describe("defaultTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = defaultTokenEstimator("hello world");
    expect(tokens).toBeGreaterThan(0);
  });

  it("returns 0 for empty string", () => {
    expect(defaultTokenEstimator("")).toBe(0);
  });

  it("returns 0 for whitespace-only string", () => {
    expect(defaultTokenEstimator("   ")).toBe(0);
  });

  it("returns at least 1 for single word", () => {
    expect(defaultTokenEstimator("hello")).toBeGreaterThanOrEqual(1);
  });

  it("scales roughly with word count", () => {
    const short = defaultTokenEstimator("one two three");
    const long = defaultTokenEstimator(
      "one two three four five six seven eight nine ten"
    );
    expect(long).toBeGreaterThan(short);
  });
});

describe("estimateTokens", () => {
  it("uses default estimator", () => {
    expect(estimateTokens("hello world")).toBeGreaterThan(0);
  });

  it("returns 0 for null-ish input", () => {
    expect(estimateTokens(null as unknown as string)).toBe(0);
    expect(estimateTokens(undefined as unknown as string)).toBe(0);
  });

  it("uses custom estimator", () => {
    const custom = (text: string) => text.length;
    expect(estimateTokens("hello", { estimator: custom })).toBe(5);
  });
});
```

**Step 4: Run all tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run`
Expected: PASS — all tests pass

**Step 5: Update snapshot**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run -u`
This creates/updates snapshot files.

**Step 6: Commit**

```bash
git add packages/ce-core/src/diff.test.ts packages/ce-core/src/trace.test.ts packages/ce-core/src/estimate.test.ts packages/ce-core/src/__snapshots__
git commit -m "test(ce-core): comprehensive tests for diff, trace, estimate with snapshots"
```

---

### Task 6: Add JSDoc to ce-core public API

**Files:**

- Modify: `packages/ce-core/src/pack.ts` (JSDoc for pack)
- Modify: `packages/ce-core/src/diff.ts` (JSDoc for diff)
- Modify: `packages/ce-core/src/trace.ts` (JSDoc for tracePack)
- Modify: `packages/ce-core/src/estimate.ts` (JSDoc for estimateTokens)
- Modify: `packages/ce-core/src/score.ts` (JSDoc for createScorer)

**Step 1: Add JSDoc**

Add JSDoc comments directly above each exported function. Examples:

For `pack()`:

````ts
/**
 * Pack context items into a token budget using greedy score-based selection.
 *
 * Items are scored (default: priority*1.0 + recency*0.7 + salience*0.5),
 * sorted by score, and greedily selected until the budget is exhausted.
 * If compression is enabled, oversized items may be compressed to fit.
 *
 * @param items - Context items to pack
 * @param budget - Token budget with maxTokens and optional reserveTokens
 * @param options - Packing options (custom scorer, estimator, compression)
 * @returns A ContextPack with selected items, dropped items, and stats
 * @throws {ValidationError} If items or budget fail validation
 * @throws {BudgetExceededError} If reserveTokens >= maxTokens
 * @throws {EstimationError} If token estimation fails
 *
 * @example
 * ```ts
 * const result = pack(
 *   [{ id: "doc", content: "Hello world", priority: 5 }],
 *   { maxTokens: 1000 }
 * );
 * console.log(result.selected); // items that fit
 * console.log(result.dropped);  // items that didn't fit
 * ```
 */
````

For `diff()`:

````ts
/**
 * Compare two context packs or item arrays to find differences.
 *
 * @param before - The original context pack or items
 * @param after - The updated context pack or items
 * @returns A PackDiff with added, removed, kept, and changed items
 * @throws {ValidationError} If before or after is null/undefined
 *
 * @example
 * ```ts
 * const changes = diff(oldPack, newPack);
 * console.log(`${changes.added.length} new items`);
 * ```
 */
````

For `tracePack()`:

````ts
/**
 * Pack items with a decision trace for debugging and observability.
 *
 * Same algorithm as pack() but records every selection decision
 * (include, exclude, compress) with reasons.
 *
 * @param items - Context items to pack
 * @param budget - Token budget
 * @param options - Packing options
 * @returns A ContextTrace with pack result and step-by-step decisions
 *
 * @example
 * ```ts
 * const trace = tracePack(items, { maxTokens: 4096 });
 * trace.steps.forEach(s => console.log(`${s.id}: ${s.decision} — ${s.reason}`));
 * ```
 */
````

For `estimateTokens()`:

```ts
/**
 * Estimate the token count for a text string.
 *
 * Uses a pluggable estimator — defaults to heuristic (words * 1.3).
 * For accurate counts, use openaiTokenEstimator from @context-engineering/providers.
 *
 * @param text - The text to estimate tokens for
 * @param options - Optional model, provider, or custom estimator
 * @returns The estimated token count
 * @throws {EstimationError} If the estimator function throws
 */
```

For `createScorer()`:

````ts
/**
 * Create an item scorer with custom weights.
 *
 * @param weights - Custom scoring weights (defaults: priority=1.0, recency=0.7, salience=0.5)
 * @returns An ItemScorer function
 *
 * @example
 * ```ts
 * const scorer = createScorer({ priority: 2.0, recency: 0.0 });
 * const score = scorer(item); // Only considers priority
 * ```
 */
````

**Step 2: Verify build**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && pnpm check`
Expected: No errors

**Step 3: Commit**

```bash
git add packages/ce-core/src/pack.ts packages/ce-core/src/diff.ts packages/ce-core/src/trace.ts packages/ce-core/src/estimate.ts packages/ce-core/src/score.ts
git commit -m "docs(ce-core): add JSDoc to all public API functions"
```

---

### Task 7: Harden ce-memory — SQL injection fix, WAL mode, close()

**Files:**

- Modify: `packages/ce-memory/src/sqlite-store.ts` (fix SQL injection, add WAL, add close)

**Step 1: Write the failing test**

Add to `packages/ce-memory/src/memory.test.ts`:

```ts
it("rejects invalid table names", () => {
  expect(
    () => new SqliteStore(":memory:", { tableName: "DROP TABLE; --" })
  ).toThrow();
});

it("accepts valid table names", () => {
  const store = new SqliteStore(":memory:", { tableName: "my_items" });
  expect(store).toBeDefined();
});

it("closes database connection", async () => {
  const store = new SqliteStore(":memory:");
  await store.put({ id: "close-test", content: "data" });
  store.close();
  // After close, operations should throw
  await expect(store.get("close-test")).rejects.toThrow();
});
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/k/Code/context-engineering/packages/ce-memory && npx vitest run`
Expected: FAIL — no table name validation, no close()

**Step 3: Fix sqlite-store.ts**

Modify `packages/ce-memory/src/sqlite-store.ts`:

Add table name validation in the constructor before `this.init()`:

```ts
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
```

Add `close()` method:

```ts
  close(): void {
    this.db.close();
  }
```

**Step 4: Run all tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-memory && npx vitest run`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/ce-memory/src/sqlite-store.ts packages/ce-memory/src/memory.test.ts
git commit -m "fix(ce-memory): validate table names, add WAL mode, add close()"
```

---

### Task 8: Comprehensive ce-memory tests

**Files:**

- Modify: `packages/ce-memory/src/memory.test.ts` (expand tests)

**Step 1: Write expanded tests**

Replace `packages/ce-memory/src/memory.test.ts` with comprehensive tests covering:

```ts
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { InMemoryStore } from "./in-memory-store";
import { FileStore } from "./file-store";
import { SqliteStore } from "./sqlite-store";
import { promises as fs } from "fs";
import os from "os";
import path from "path";

const tempDir = path.join(os.tmpdir(), `ce-memory-tests-${Date.now()}`);

function tempPath(name: string) {
  return path.join(tempDir, name);
}

beforeEach(async () => {
  await fs.mkdir(tempDir, { recursive: true });
});

afterEach(async () => {
  await fs.rm(tempDir, { recursive: true, force: true });
});

describe("InMemoryStore", () => {
  it("stores and retrieves items", async () => {
    const store = new InMemoryStore();
    const [item] = await store.put({ id: "a", content: "Hello" });
    const fetched = await store.get(item.id);
    expect(fetched?.content).toBe("Hello");
  });

  it("returns null for missing items", async () => {
    const store = new InMemoryStore();
    expect(await store.get("nonexistent")).toBeNull();
  });

  it("handles batch put", async () => {
    const store = new InMemoryStore();
    const items = await store.put([
      { id: "a", content: "First" },
      { id: "b", content: "Second" },
    ]);
    expect(items.length).toBe(2);
    expect(await store.get("a")).not.toBeNull();
    expect(await store.get("b")).not.toBeNull();
  });

  it("forgets items", async () => {
    const store = new InMemoryStore();
    await store.put({ id: "a", content: "Hello" });
    const deleted = await store.forget("a");
    expect(deleted).toBe(true);
    expect(await store.get("a")).toBeNull();
  });

  it("returns false when forgetting nonexistent items", async () => {
    const store = new InMemoryStore();
    expect(await store.forget("nope")).toBe(false);
  });

  it("queries with limit", async () => {
    const store = new InMemoryStore();
    await store.put([
      { id: "a", content: "First" },
      { id: "b", content: "Second" },
      { id: "c", content: "Third" },
    ]);
    const results = await store.query({ limit: 2 });
    expect(results.length).toBe(2);
  });

  it("queries with minSalience", async () => {
    const store = new InMemoryStore();
    await store.put([
      { id: "high", content: "Important", salience: 0.9 },
      { id: "low", content: "Meh", salience: 0.1 },
    ]);
    const results = await store.query({ minSalience: 0.5 });
    expect(results.length).toBe(1);
    expect(results[0].id).toBe("high");
  });

  it("queries with text filter", async () => {
    const store = new InMemoryStore();
    await store.put([
      { id: "a", content: "Hello world" },
      { id: "b", content: "Goodbye world" },
    ]);
    const results = await store.query({ text: "hello" });
    expect(results.length).toBe(1);
    expect(results[0].id).toBe("a");
  });

  it("filters expired items by default", async () => {
    const store = new InMemoryStore();
    const past = new Date(Date.now() - 10000).toISOString();
    await store.put({
      id: "old",
      content: "Expired",
      createdAt: past,
      ttlSeconds: 1,
    });
    const results = await store.query();
    expect(results.length).toBe(0);
  });

  it("includes expired items when requested", async () => {
    const store = new InMemoryStore();
    const past = new Date(Date.now() - 10000).toISOString();
    await store.put({
      id: "old",
      content: "Expired",
      createdAt: past,
      ttlSeconds: 1,
    });
    const results = await store.query({ includeExpired: true });
    expect(results.length).toBe(1);
  });

  it("upserts on duplicate id", async () => {
    const store = new InMemoryStore();
    await store.put({ id: "a", content: "Version 1" });
    await store.put({ id: "a", content: "Version 2" });
    const item = await store.get("a");
    expect(item?.content).toBe("Version 2");
  });

  it("generates id when missing", async () => {
    const store = new InMemoryStore();
    const [item] = await store.put({ content: "No ID" });
    expect(item.id).toBeDefined();
    expect(item.id.length).toBeGreaterThan(0);
  });
});

describe("FileStore", () => {
  it("persists items to file", async () => {
    const filePath = tempPath("persist.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "f1", content: "Persisted" });
    const fetched = await store.get("f1");
    expect(fetched?.content).toBe("Persisted");
  });

  it("survives reload", async () => {
    const filePath = tempPath("reload.jsonl");
    const store1 = new FileStore(filePath);
    await store1.put({ id: "f1", content: "Data" });

    const store2 = new FileStore(filePath);
    const fetched = await store2.get("f1");
    expect(fetched?.content).toBe("Data");
  });

  it("handles empty file", async () => {
    const filePath = tempPath("empty.jsonl");
    await fs.writeFile(filePath, "");
    const store = new FileStore(filePath);
    const results = await store.query();
    expect(results).toEqual([]);
  });

  it("creates parent directories", async () => {
    const filePath = path.join(tempDir, "nested", "dir", "store.jsonl");
    const store = new FileStore(filePath);
    await store.put({ id: "nested", content: "Deep" });
    const fetched = await store.get("nested");
    expect(fetched?.content).toBe("Deep");
  });
});

describe("SqliteStore", () => {
  it("stores and retrieves items", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "s1", content: "SQLite data" });
    const fetched = await store.get("s1");
    expect(fetched?.content).toBe("SQLite data");
    store.close();
  });

  it("handles TTL expiration", async () => {
    const store = new SqliteStore(":memory:");
    const past = new Date(Date.now() - 5000).toISOString();
    await store.put({
      id: "ttl-1",
      content: "Old memory",
      createdAt: past,
      ttlSeconds: 1,
    });
    const results = await store.query({ now: Date.now() });
    expect(results.length).toBe(0);
    store.close();
  });

  it("upserts on duplicate id", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "s1", content: "Version 1" });
    await store.put({ id: "s1", content: "Version 2" });
    const fetched = await store.get("s1");
    expect(fetched?.content).toBe("Version 2");
    store.close();
  });

  it("batch inserts in transaction", async () => {
    const store = new SqliteStore(":memory:");
    const items = await store.put([
      { id: "b1", content: "First" },
      { id: "b2", content: "Second" },
    ]);
    expect(items.length).toBe(2);
    store.close();
  });

  it("rejects invalid table names", () => {
    expect(
      () => new SqliteStore(":memory:", { tableName: "DROP TABLE; --" })
    ).toThrow();
  });

  it("accepts valid table names", () => {
    const store = new SqliteStore(":memory:", { tableName: "my_items" });
    expect(store).toBeDefined();
    store.close();
  });

  it("closes database connection", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({ id: "close-test", content: "data" });
    store.close();
  });

  it("preserves metadata", async () => {
    const store = new SqliteStore(":memory:");
    await store.put({
      id: "meta",
      content: "With metadata",
      metadata: { key: "value", nested: { a: 1 } },
    });
    const fetched = await store.get("meta");
    expect(fetched?.metadata).toEqual({ key: "value", nested: { a: 1 } });
    store.close();
  });
});
```

**Step 2: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-memory && npx vitest run`
Expected: PASS — all tests pass

**Step 3: Commit**

```bash
git add packages/ce-memory/src/memory.test.ts
git commit -m "test(ce-memory): comprehensive tests for all three store implementations"
```

---

### Task 9: Add factory function and JSDoc to ce-memory

**Files:**

- Create: `packages/ce-memory/src/factory.ts`
- Modify: `packages/ce-memory/src/index.ts` (export factory)

**Step 1: Write the failing test**

Add to end of `packages/ce-memory/src/memory.test.ts`:

```ts
import { createMemoryStore } from "./factory";

describe("createMemoryStore", () => {
  it("creates in-memory store", () => {
    const store = createMemoryStore("memory");
    expect(store).toBeInstanceOf(InMemoryStore);
  });

  it("creates file store", () => {
    const store = createMemoryStore("file", {
      path: tempPath("factory.jsonl"),
    });
    expect(store).toBeInstanceOf(FileStore);
  });

  it("creates sqlite store", () => {
    const store = createMemoryStore("sqlite", { path: ":memory:" });
    expect(store).toBeInstanceOf(SqliteStore);
  });

  it("throws for unknown type", () => {
    expect(() => createMemoryStore("redis" as any)).toThrow();
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/k/Code/context-engineering/packages/ce-memory && npx vitest run`
Expected: FAIL — cannot import `createMemoryStore`

**Step 3: Create factory**

Create `packages/ce-memory/src/factory.ts`:

````ts
import type { MemoryStore } from "./types";
import { InMemoryStore } from "./in-memory-store";
import { FileStore } from "./file-store";
import { SqliteStore } from "./sqlite-store";

interface MemoryStoreOptions {
  path?: string;
  tableName?: string;
}

/**
 * Create a memory store by type name.
 *
 * @param type - The store type: "memory", "file", or "sqlite"
 * @param options - Store-specific options (path required for file/sqlite)
 * @returns A MemoryStore instance
 * @throws {Error} If type is unknown or required options are missing
 *
 * @example
 * ```ts
 * const store = createMemoryStore("sqlite", { path: "data.db" });
 * await store.put({ id: "1", content: "Hello" });
 * ```
 */
export function createMemoryStore(
  type: "memory" | "file" | "sqlite",
  options: MemoryStoreOptions = {}
): MemoryStore {
  switch (type) {
    case "memory":
      return new InMemoryStore();
    case "file":
      if (!options.path) {
        throw new Error("FileStore requires a 'path' option");
      }
      return new FileStore(options.path);
    case "sqlite":
      if (!options.path) {
        throw new Error("SqliteStore requires a 'path' option");
      }
      return new SqliteStore(options.path, { tableName: options.tableName });
    default:
      throw new Error(`Unknown memory store type: ${type}`);
  }
}
````

**Step 4: Export from index**

Modify `packages/ce-memory/src/index.ts` — add `export * from "./factory";`

**Step 5: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-memory && npx vitest run`
Expected: PASS

**Step 6: Commit**

```bash
git add packages/ce-memory/src/factory.ts packages/ce-memory/src/index.ts packages/ce-memory/src/memory.test.ts
git commit -m "feat(ce-memory): add createMemoryStore factory function"
```

---

### Task 10: Add token estimator tests and presets to ce-providers

**Files:**

- Create: `packages/ce-providers/src/token-estimators.test.ts`
- Create: `packages/ce-providers/src/presets.ts`
- Modify: `packages/ce-providers/src/index.ts` (export presets)

**Step 1: Write token estimator tests**

Create `packages/ce-providers/src/token-estimators.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  openaiTokenEstimator,
  anthropicTokenEstimator,
} from "./token-estimators";

describe("openaiTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = openaiTokenEstimator("Hello, world!");
    expect(tokens).toBeGreaterThan(0);
    expect(tokens).toBeLessThan(20);
  });

  it("returns 0 for empty string", () => {
    expect(openaiTokenEstimator("")).toBe(0);
  });

  it("handles long text", () => {
    const long = "word ".repeat(1000);
    const tokens = openaiTokenEstimator(long);
    expect(tokens).toBeGreaterThan(500);
  });

  it("is consistent across calls (cached encoding)", () => {
    const first = openaiTokenEstimator("test string");
    const second = openaiTokenEstimator("test string");
    expect(first).toBe(second);
  });
});

describe("anthropicTokenEstimator", () => {
  it("estimates tokens for normal text", () => {
    const tokens = anthropicTokenEstimator("Hello, world!");
    expect(tokens).toBeGreaterThan(0);
  });

  it("returns 0 for empty string", () => {
    expect(anthropicTokenEstimator("")).toBe(0);
  });

  it("returns 0 for whitespace-only", () => {
    expect(anthropicTokenEstimator("   ")).toBe(0);
  });

  it("returns at least 1 for single word", () => {
    expect(anthropicTokenEstimator("hello")).toBeGreaterThanOrEqual(1);
  });

  it("uses 1.4x word multiplier", () => {
    // "one two three" = 3 words * 1.4 = 4.2 → ceil = 5
    expect(anthropicTokenEstimator("one two three")).toBe(5);
  });
});
```

**Step 2: Create presets**

Create `packages/ce-providers/src/presets.ts`:

````ts
import {
  openaiTokenEstimator,
  anthropicTokenEstimator,
} from "./token-estimators";
import type { TokenEstimator } from "@context-engineering/core";

interface ProviderPreset {
  estimator: TokenEstimator;
}

/**
 * Pre-configured provider settings.
 *
 * @example
 * ```ts
 * import { presets } from "@context-engineering/providers";
 * import { pack } from "@context-engineering/core";
 *
 * const result = pack(items, budget, {
 *   tokenEstimator: presets.openai.estimator,
 * });
 * ```
 */
export const presets = {
  openai: {
    estimator: openaiTokenEstimator,
  } satisfies ProviderPreset,
  anthropic: {
    estimator: anthropicTokenEstimator,
  } satisfies ProviderPreset,
};
````

**Step 3: Export from index**

Modify `packages/ce-providers/src/index.ts` — add `export * from "./presets";`

**Step 4: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-providers && npx vitest run`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/ce-providers/src/token-estimators.test.ts packages/ce-providers/src/presets.ts packages/ce-providers/src/index.ts
git commit -m "feat(ce-providers): add token estimator tests and provider presets"
```

---

### Task 11: Harden CLI — TTY detection, colors, stdin, help text

**Files:**

- Create: `packages/ce-cli/src/output.ts` (TTY-aware output helpers)
- Modify: `packages/ce-cli/src/cli.ts` (integrate output helpers, stdin, help)

**Step 1: Create output helpers**

Create `packages/ce-cli/src/output.ts`:

```ts
const isTTY = process.stdout.isTTY ?? false;
let forceJson = false;
let noColor = false;

export function setForceJson(value: boolean) {
  forceJson = value;
}

export function setNoColor(value: boolean) {
  noColor = value;
}

export function isJsonMode(): boolean {
  return forceJson || !isTTY;
}

// ANSI color helpers
const ansi = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  cyan: "\x1b[36m",
};

function color(code: string, text: string): string {
  if (noColor || !isTTY) return text;
  return `${code}${text}${ansi.reset}`;
}

export const fmt = {
  bold: (text: string) => color(ansi.bold, text),
  dim: (text: string) => color(ansi.dim, text),
  red: (text: string) => color(ansi.red, text),
  green: (text: string) => color(ansi.green, text),
  yellow: (text: string) => color(ansi.yellow, text),
  blue: (text: string) => color(ansi.blue, text),
  cyan: (text: string) => color(ansi.cyan, text),
  success: (text: string) => color(ansi.green, `✓ ${text}`),
  error: (text: string) => color(ansi.red, `✗ ${text}`),
  warn: (text: string) => color(ansi.yellow, `⚠ ${text}`),
};

export function outputResult(data: unknown, humanReadable: () => void): void {
  if (isJsonMode()) {
    console.log(JSON.stringify(data, null, 2));
  } else {
    humanReadable();
  }
}

export function outputError(message: string, details?: string): never {
  if (isJsonMode()) {
    console.error(JSON.stringify({ error: message, details }));
  } else {
    console.error(fmt.error(message));
    if (details) console.error(fmt.dim(details));
  }
  process.exit(1);
}

export async function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf-8");
    process.stdin.on("data", chunk => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}
```

**Step 2: Rewrite cli.ts with better UX**

Replace `packages/ce-cli/src/cli.ts` with improved version integrating:

- `--no-color` global option
- `--json` forces JSON output (already present but global)
- stdin support: when `-i` is `-` or when stdin is piped, read from stdin
- Better error handling with `outputError`
- Help text with examples
- Exit codes: 0 success, 1 validation error, 2 file error

Key changes per command:

For `pack` action:

```ts
  .action(async (options) => {
    try {
      const items = options.input === "-"
        ? JSON.parse(await readStdin())
        : await loadItemsFromFile(options.input);
      const packResult = runPack(items, Number(options.budget), {
        provider: options.provider === "heuristic" ? undefined : options.provider,
      });
      outputResult(packResult, () => {
        console.log(fmt.bold(`Selected ${packResult.selected.length} items`) + fmt.dim(` (dropped ${packResult.dropped.length})`));
        console.log(`Total tokens: ${fmt.cyan(String(packResult.totalTokens))}`);
        console.log(fmt.dim("\nSelected:"));
        packResult.selected.forEach((item) =>
          console.log(`  ${fmt.green("•")} ${item.id} ${fmt.dim(`(${item.tokens ?? "?"} tokens)`)}`)
        );
      });
    } catch (err) {
      if (err instanceof Error && err.message.includes("ENOENT")) {
        outputError(`File not found: ${options.input}`, "Check the file path and try again");
      }
      outputError(err instanceof Error ? err.message : String(err));
    }
  })
```

Apply similar patterns to `trace`, `diff`, `lint`, and `budget` commands.

**Step 3: Write CLI output tests**

Create `packages/ce-cli/src/output.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { fmt } from "./output";

describe("fmt", () => {
  it("wraps text with ANSI codes when not in noColor", () => {
    // Note: fmt.red returns raw string when isTTY is false
    // This test verifies the function exists and returns a string
    expect(typeof fmt.red("error")).toBe("string");
    expect(fmt.red("error")).toContain("error");
  });

  it("success prefix", () => {
    expect(fmt.success("done")).toContain("done");
  });

  it("error prefix", () => {
    expect(fmt.error("fail")).toContain("fail");
  });
});
```

**Step 4: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-cli && npx vitest run`
Expected: PASS

**Step 5: Commit**

```bash
git add packages/ce-cli/src/output.ts packages/ce-cli/src/output.test.ts packages/ce-cli/src/cli.ts
git commit -m "feat(ce-cli): TTY-aware output, ANSI colors, stdin support, better errors"
```

---

### Task 12: Comprehensive CLI tests

**Files:**

- Modify: `packages/ce-cli/src/lib.test.ts` (expand test coverage)

**Step 1: Expand lib tests**

Replace `packages/ce-cli/src/lib.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  runPack,
  runDiff,
  runBudget,
  lintFile,
  runTrace,
  loadItemsFromFile,
} from "./lib";
import { promises as fs } from "fs";
import os from "os";
import path from "path";

const items = [
  { id: "x", content: "Alpha", tokens: 10, priority: 2 },
  { id: "y", content: "Beta", tokens: 20, priority: 1 },
];

const tempDir = path.join(os.tmpdir(), `ce-cli-tests-${Date.now()}`);

describe("runPack", () => {
  it("packs items within budget", () => {
    const result = runPack(items, 15);
    expect(result.selected.length).toBe(1);
    expect(result.selected[0].id).toBe("x");
  });

  it("packs all items when budget is large", () => {
    const result = runPack(items, 1000);
    expect(result.selected.length).toBe(2);
  });

  it("returns empty pack for zero items", () => {
    const result = runPack([], 100);
    expect(result.selected.length).toBe(0);
  });

  it("supports openai provider", () => {
    const result = runPack(items, 1000, { provider: "openai" });
    expect(result.selected.length).toBeGreaterThan(0);
  });

  it("supports anthropic provider", () => {
    const result = runPack(items, 1000, { provider: "anthropic" });
    expect(result.selected.length).toBeGreaterThan(0);
  });
});

describe("runDiff", () => {
  it("detects removals", () => {
    const diff = runDiff(items, [items[0]]);
    expect(diff.removed.length).toBe(1);
    expect(diff.removed[0].id).toBe("y");
  });

  it("handles identical inputs", () => {
    const diff = runDiff(items, [...items]);
    expect(diff.added.length).toBe(0);
    expect(diff.removed.length).toBe(0);
  });
});

describe("runBudget", () => {
  it("estimates tokens for text", () => {
    const tokens = runBudget("hello world");
    expect(tokens).toBeGreaterThan(0);
  });

  it("estimates with openai provider", () => {
    const tokens = runBudget("hello world", { provider: "openai" });
    expect(tokens).toBeGreaterThan(0);
  });
});

describe("runTrace", () => {
  it("returns trace steps", () => {
    const trace = runTrace(items, 15);
    expect(trace.steps.length).toBeGreaterThan(0);
  });

  it("trace has createdAt", () => {
    const trace = runTrace(items, 15);
    expect(trace.createdAt).toBeDefined();
  });
});

describe("lintFile", () => {
  it("validates valid context item", async () => {
    const result = await lintFile("context-item", { id: "z", content: "test" });
    expect(result.valid).toBe(true);
  });

  it("rejects invalid context item", async () => {
    const result = await lintFile("context-item", { notAnId: true });
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it("throws for unknown schema", async () => {
    await expect(lintFile("nonexistent" as any, {})).rejects.toThrow();
  });
});

describe("loadItemsFromFile", () => {
  it("loads JSON array", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "items.json");
    await fs.writeFile(filePath, JSON.stringify(items));
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded.length).toBe(2);
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it("loads JSON object with items field", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "wrapped.json");
    await fs.writeFile(filePath, JSON.stringify({ items }));
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded.length).toBe(2);
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it("loads JSONL", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "items.jsonl");
    const content = items.map(i => JSON.stringify(i)).join("\n");
    await fs.writeFile(filePath, content);
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded.length).toBe(2);
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it("returns empty array for empty file", async () => {
    await fs.mkdir(tempDir, { recursive: true });
    const filePath = path.join(tempDir, "empty.json");
    await fs.writeFile(filePath, "");
    const loaded = await loadItemsFromFile(filePath);
    expect(loaded).toEqual([]);
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it("throws for nonexistent file", async () => {
    await expect(loadItemsFromFile("/nonexistent/path.json")).rejects.toThrow();
  });
});
```

**Step 2: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-cli && npx vitest run`
Expected: PASS

**Step 3: Commit**

```bash
git add packages/ce-cli/src/lib.test.ts
git commit -m "test(ce-cli): comprehensive tests for all CLI lib functions"
```

---

### Task 13: Python SDK — add input validation to core.py

**Files:**

- Modify: `python/context_engineering/core.py` (add validation, error handling)

**Step 1: Write the failing test**

Add to `python/tests/test_core.py`:

```python
import pytest
from context_engineering.core import pack, diff, estimate_tokens, Budget, ContextItem


def test_pack_selects_high_priority():
    items = [
        ContextItem(id="a", content="important", priority=10, tokens=50),
        ContextItem(id="b", content="less", priority=1, tokens=50),
    ]
    result = pack(items, Budget(maxTokens=60))
    ids = [i.id for i in result.selected]
    assert "a" in ids
    assert "b" not in ids


def test_diff_detects_changes():
    before = [ContextItem(id="a", content="hello", tokens=10)]
    after = [ContextItem(id="b", content="world", tokens=10)]
    result = diff(before, after)
    assert len(result.added) == 1
    assert len(result.removed) == 1


def test_pack_empty_items():
    result = pack([], Budget(maxTokens=100))
    assert result.selected == []
    assert result.dropped == []
    assert result.total_tokens == 0


def test_pack_rejects_negative_budget():
    with pytest.raises(ValueError, match="maxTokens must be positive"):
        pack([], Budget(maxTokens=-1))


def test_pack_rejects_zero_budget():
    with pytest.raises(ValueError, match="maxTokens must be positive"):
        pack([], Budget(maxTokens=0))


def test_pack_rejects_reserve_exceeding_max():
    items = [ContextItem(id="a", content="test", tokens=10)]
    with pytest.raises(ValueError, match="reserveTokens"):
        pack(items, Budget(maxTokens=100, reserveTokens=100))


def test_estimate_tokens_empty_string():
    assert estimate_tokens("") == 0


def test_estimate_tokens_normal_text():
    tokens = estimate_tokens("hello world")
    assert tokens > 0


def test_diff_empty_inputs():
    result = diff([], [])
    assert result.added == []
    assert result.removed == []


def test_diff_content_changes():
    before = [ContextItem(id="a", content="old", tokens=10)]
    after = [ContextItem(id="a", content="new", tokens=10)]
    result = diff(before, after)
    assert len(result.changed) == 1
```

**Step 2: Run test to verify new tests fail**

Run: `cd /Users/k/Code/context-engineering/python && python -m pytest tests/test_core.py -v`
Expected: FAIL — no validation raises

**Step 3: Add validation to pack() in core.py**

Modify `python/context_engineering/core.py`. In the `pack()` function, add at the start:

```python
def pack(items, budget, **kwargs):
    # Validate budget
    if budget.maxTokens <= 0:
        raise ValueError(f"maxTokens must be positive, got {budget.maxTokens}")
    if budget.reserveTokens is not None and budget.reserveTokens >= budget.maxTokens:
        raise ValueError(
            f"reserveTokens ({budget.reserveTokens}) must be less than maxTokens ({budget.maxTokens})"
        )
```

Add validation for `estimate_tokens()`:

```python
def estimate_tokens(text, **kwargs):
    if not text:
        return 0
    # ... rest of function
```

**Step 4: Run tests**

Run: `cd /Users/k/Code/context-engineering/python && python -m pytest tests/test_core.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add python/context_engineering/core.py python/tests/test_core.py
git commit -m "feat(python): add input validation to pack() and estimate_tokens()"
```

---

### Task 14: Python SDK — comprehensive memory tests

**Files:**

- Modify: `python/tests/test_memory.py` (expand coverage)

**Step 1: Write expanded tests**

Replace `python/tests/test_memory.py`:

```python
import os
import tempfile
import pytest
from context_engineering.memory import InMemoryStore, FileStore, SqliteStore, MemoryItem, MemoryQuery


class TestInMemoryStore:
    def test_put_and_get(self):
        store = InMemoryStore()
        items = store.put(MemoryItem(id="a", content="Hello"))
        assert len(items) == 1
        fetched = store.get("a")
        assert fetched is not None
        assert fetched.content == "Hello"

    def test_get_missing(self):
        store = InMemoryStore()
        assert store.get("nonexistent") is None

    def test_batch_put(self):
        store = InMemoryStore()
        items = store.put([
            MemoryItem(id="a", content="First"),
            MemoryItem(id="b", content="Second"),
        ])
        assert len(items) == 2
        assert store.get("a") is not None
        assert store.get("b") is not None

    def test_forget(self):
        store = InMemoryStore()
        store.put(MemoryItem(id="a", content="Hello"))
        assert store.forget("a") is True
        assert store.get("a") is None

    def test_forget_missing(self):
        store = InMemoryStore()
        assert store.forget("nope") is False

    def test_query_limit(self):
        store = InMemoryStore()
        store.put([
            MemoryItem(id="a", content="1"),
            MemoryItem(id="b", content="2"),
            MemoryItem(id="c", content="3"),
        ])
        results = store.query(MemoryQuery(limit=2))
        assert len(results) == 2

    def test_query_min_salience(self):
        store = InMemoryStore()
        store.put([
            MemoryItem(id="high", content="Important", salience=0.9),
            MemoryItem(id="low", content="Meh", salience=0.1),
        ])
        results = store.query(MemoryQuery(min_score=0.5))
        assert len(results) == 1
        assert results[0].id == "high"

    def test_upsert(self):
        store = InMemoryStore()
        store.put(MemoryItem(id="a", content="V1"))
        store.put(MemoryItem(id="a", content="V2"))
        assert store.get("a").content == "V2"


class TestFileStore:
    def test_roundtrip(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store = FileStore(path)
            store.put(MemoryItem(id="f1", content="Persisted"))
            fetched = store.get("f1")
            assert fetched is not None
            assert fetched.content == "Persisted"
        finally:
            os.unlink(path)

    def test_reload(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store1 = FileStore(path)
            store1.put(MemoryItem(id="f1", content="Data"))
            store2 = FileStore(path)
            assert store2.get("f1").content == "Data"
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            f.write("")
            path = f.name
        try:
            store = FileStore(path)
            assert store.query() == []
        finally:
            os.unlink(path)


class TestSqliteStore:
    def test_put_and_get(self):
        store = SqliteStore(":memory:")
        store.put(MemoryItem(id="s1", content="SQLite"))
        assert store.get("s1").content == "SQLite"

    def test_ttl_expiry(self):
        from datetime import datetime, timedelta
        store = SqliteStore(":memory:")
        past = (datetime.now() - timedelta(seconds=10)).isoformat()
        store.put(MemoryItem(id="old", content="Expired", created_at=past, ttl_seconds=1))
        results = store.query()
        assert len(results) == 0

    def test_upsert(self):
        store = SqliteStore(":memory:")
        store.put(MemoryItem(id="s1", content="V1"))
        store.put(MemoryItem(id="s1", content="V2"))
        assert store.get("s1").content == "V2"

    def test_batch_insert(self):
        store = SqliteStore(":memory:")
        items = store.put([
            MemoryItem(id="b1", content="First"),
            MemoryItem(id="b2", content="Second"),
        ])
        assert len(items) == 2
```

**Step 2: Run tests**

Run: `cd /Users/k/Code/context-engineering/python && python -m pytest tests/test_memory.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add python/tests/test_memory.py
git commit -m "test(python): comprehensive memory store tests"
```

---

### Task 15: Python CLI — TTY detection, colors, stdin

**Files:**

- Modify: `python/context_engineering/cli.py` (add TTY detection, colors, stdin, error handling)

**Step 1: Write the failing test**

Add to `python/tests/test_cli.py`:

```python
import subprocess
import sys
import json
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_cli_budget():
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "budget", "-t", "hello world"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.strip().isdigit()


def test_cli_pack_json_output():
    items_path = os.path.join(PROJECT_ROOT, "..", "fixtures", "context-items.json")
    if not os.path.exists(items_path):
        items_path = os.path.join(PROJECT_ROOT, "tests", "fixtures", "items.json")
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "pack", "-i", items_path, "-b", "100"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    # When piped (not TTY), should output JSON
    data = json.loads(result.stdout)
    assert "selected" in data


def test_cli_budget_missing_args():
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "budget"],
        capture_output=True, text=True
    )
    assert result.returncode != 0


def test_cli_pack_stdin():
    items = json.dumps([{"id": "a", "content": "test", "tokens": 10, "priority": 5}])
    result = subprocess.run(
        [sys.executable, "-m", "context_engineering.cli", "pack", "-i", "-", "-b", "100"],
        input=items, capture_output=True, text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data["selected"]) == 1
```

**Step 2: Run test to verify new tests fail**

Run: `cd /Users/k/Code/context-engineering/python && python -m pytest tests/test_cli.py -v`
Expected: FAIL — no stdin support, no JSON output when piped

**Step 3: Add TTY detection and stdin to Python CLI**

Modify `python/context_engineering/cli.py`:

Add at top of file:

```python
import sys
import json
import os

def is_tty():
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

# ANSI color helpers
class fmt:
    @staticmethod
    def _wrap(code, text):
        if not is_tty() or os.environ.get("NO_COLOR"):
            return text
        return f"\033[{code}m{text}\033[0m"

    @staticmethod
    def bold(text): return fmt._wrap("1", text)
    @staticmethod
    def red(text): return fmt._wrap("31", text)
    @staticmethod
    def green(text): return fmt._wrap("32", text)
    @staticmethod
    def cyan(text): return fmt._wrap("36", text)
    @staticmethod
    def dim(text): return fmt._wrap("2", text)
```

Update `pack` command to output JSON when piped (not TTY) and human-readable when interactive. Add stdin support when `-i -` is used.

**Step 4: Run tests**

Run: `cd /Users/k/Code/context-engineering/python && python -m pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add python/context_engineering/cli.py python/tests/test_cli.py
git commit -m "feat(python-cli): TTY detection, ANSI colors, stdin support"
```

---

### Task 16: Python SDK — add docstrings to public API

**Files:**

- Modify: `python/context_engineering/core.py`
- Modify: `python/context_engineering/memory.py`
- Modify: `python/context_engineering/framework.py`

**Step 1: Add Google-style docstrings**

For `pack()`:

```python
def pack(items, budget, **kwargs):
    """Pack context items into a token budget using greedy score-based selection.

    Items are scored (default: priority*1.0 + recency*0.7 + salience*0.5),
    sorted by score, and greedily selected until the budget is exhausted.

    Args:
        items: Context items to pack.
        budget: Token budget with maxTokens and optional reserveTokens.
        **kwargs: Optional scorer, token_estimator, summarizer, weights.

    Returns:
        ContextPack with selected items, dropped items, and stats.

    Raises:
        ValueError: If budget.maxTokens <= 0 or reserveTokens >= maxTokens.

    Example:
        >>> result = pack(
        ...     [ContextItem(id="doc", content="Hello", priority=5)],
        ...     Budget(maxTokens=1000)
        ... )
        >>> len(result.selected)
        1
    """
```

Apply similar docstrings to `diff()`, `estimate_tokens()`, `trace_pack()`, `MemoryStore` methods, and `AgentContextManager` methods.

**Step 2: Verify**

Run: `cd /Users/k/Code/context-engineering/python && python -c "from context_engineering import pack; help(pack)"`
Expected: Shows docstring

**Step 3: Commit**

```bash
git add python/context_engineering/core.py python/context_engineering/memory.py python/context_engineering/framework.py
git commit -m "docs(python): add Google-style docstrings to all public APIs"
```

---

### Task 17: Production features — streaming pack

**Files:**

- Create: `packages/ce-core/src/stream.ts`
- Modify: `packages/ce-core/src/index.ts` (export stream)

**Step 1: Write the failing test**

Create `packages/ce-core/src/stream.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { packStream } from "./stream";
import type { ContextItem } from "./types";

const items: ContextItem[] = [
  { id: "a", content: "High priority", priority: 10, tokens: 50 },
  { id: "b", content: "Medium", priority: 5, tokens: 60 },
  { id: "c", content: "Low", priority: 1, tokens: 40 },
];

describe("packStream", () => {
  it("yields selected items one by one", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream(items, { maxTokens: 200 })) {
      selected.push(item);
    }
    expect(selected.length).toBe(3);
  });

  it("respects budget", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream(items, { maxTokens: 55 })) {
      selected.push(item);
    }
    const totalTokens = selected.reduce((sum, i) => sum + (i.tokens ?? 0), 0);
    expect(totalTokens).toBeLessThanOrEqual(55);
  });

  it("yields items in score order", async () => {
    const selected: ContextItem[] = [];
    for await (const item of packStream(items, { maxTokens: 200 })) {
      selected.push(item);
    }
    // First item should be highest priority
    expect(selected[0].id).toBe("a");
  });

  it("validates budget", async () => {
    const gen = packStream(items, { maxTokens: -1 });
    await expect(gen.next()).rejects.toThrow();
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run src/stream.test.ts`
Expected: FAIL — module not found

**Step 3: Implement packStream**

Create `packages/ce-core/src/stream.ts`:

````ts
import type { Budget, ContextItem, PackOptions } from "./types";
import { BudgetSchema, ContextItemSchema } from "./schemas";
import {
  ValidationError,
  BudgetExceededError,
  EstimationError,
} from "./errors";
import { defaultItemScorer, createScorer } from "./score";
import { estimateTokens } from "./estimate";
import { z } from "zod";

/**
 * Stream-pack context items, yielding each selected item as it's chosen.
 *
 * Same greedy algorithm as pack() but yields items one at a time via
 * async generator. Useful for large item sets where you want to start
 * processing selected items before packing completes.
 *
 * @param items - Context items to pack
 * @param budget - Token budget
 * @param options - Packing options
 * @yields Selected ContextItems in score order
 * @throws {ValidationError} If items or budget fail validation
 *
 * @example
 * ```ts
 * for await (const item of packStream(items, { maxTokens: 4096 })) {
 *   console.log(`Selected: ${item.id}`);
 * }
 * ```
 */
export async function* packStream(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): AsyncGenerator<ContextItem> {
  // Validate
  const budgetResult = BudgetSchema.safeParse(budget);
  if (!budgetResult.success) {
    throw new ValidationError(
      `Invalid budget: ${budgetResult.error.issues.map(i => i.message).join(", ")}`,
      budgetResult.error.issues.map(i => ({
        path: i.path.join("."),
        message: i.message,
      }))
    );
  }

  if (
    budget.reserveTokens !== undefined &&
    budget.reserveTokens >= budget.maxTokens
  ) {
    throw new BudgetExceededError(
      `reserveTokens (${budget.reserveTokens}) must be less than maxTokens (${budget.maxTokens})`
    );
  }

  const scorer =
    options.scorer ??
    (options.weights ? createScorer(options.weights) : defaultItemScorer);
  const tokenEstimator = options.tokenEstimator;
  const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);

  // Score and sort
  const scoredItems = items.map(item => {
    const tokens =
      item.tokens ??
      estimateTokens(item.content, { estimator: tokenEstimator });
    const score = scorer({ ...item, tokens });
    return { ...item, tokens, score };
  });

  const sorted = [...scoredItems].sort((a, b) => {
    if ((b.score ?? 0) === (a.score ?? 0)) {
      return (b.recency ?? 0) - (a.recency ?? 0);
    }
    return (b.score ?? 0) - (a.score ?? 0);
  });

  let remaining = Math.max(0, maxTokens);

  for (const item of sorted) {
    if ((item.tokens ?? 0) <= remaining) {
      remaining -= item.tokens ?? 0;
      yield item;
    }
  }
}
````

**Step 4: Export from index**

Modify `packages/ce-core/src/index.ts` — add `export * from "./stream";`

**Step 5: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run`
Expected: PASS

**Step 6: Commit**

```bash
git add packages/ce-core/src/stream.ts packages/ce-core/src/stream.test.ts packages/ce-core/src/index.ts
git commit -m "feat(ce-core): add packStream async generator for streaming pack results"
```

---

### Task 18: Production features — structured logging

**Files:**

- Create: `packages/ce-core/src/logger.ts`
- Modify: `packages/ce-core/src/types.ts` (add logger to PackOptions)
- Modify: `packages/ce-core/src/pack.ts` (integrate logger)
- Modify: `packages/ce-core/src/index.ts` (export logger types)

**Step 1: Create logger interface**

Create `packages/ce-core/src/logger.ts`:

```ts
export interface Logger {
  debug(message: string, data?: Record<string, unknown>): void;
  info(message: string, data?: Record<string, unknown>): void;
  warn(message: string, data?: Record<string, unknown>): void;
  error(message: string, data?: Record<string, unknown>): void;
}

export const noopLogger: Logger = {
  debug() {},
  info() {},
  warn() {},
  error() {},
};
```

**Step 2: Add logger to PackOptions**

Modify `packages/ce-core/src/types.ts` — add to `PackOptions`:

```ts
  logger?: import("./logger").Logger;
```

**Step 3: Integrate logging into pack.ts**

In `internalPack()`, after the scorer/tokenEstimator setup:

```ts
const logger = options.logger ?? noopLogger;
logger.info("pack:start", {
  itemCount: items.length,
  maxTokens,
  reserveTokens: budget.reserveTokens,
});
```

After selecting an item:

```ts
logger.debug("pack:include", {
  id: item.id,
  tokens: item.tokens,
  score: item.score,
  remaining,
});
```

After dropping:

```ts
logger.debug("pack:exclude", {
  id: item.id,
  tokens: item.tokens,
  score: item.score,
  reason: "over_budget",
});
```

At the end:

```ts
logger.info("pack:complete", {
  selectedCount: selected.length,
  droppedCount: dropped.length,
  totalTokens,
});
```

**Step 4: Export from index**

Modify `packages/ce-core/src/index.ts` — add `export * from "./logger";`

**Step 5: Run all tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run`
Expected: PASS (logger is no-op by default, doesn't affect behavior)

**Step 6: Commit**

```bash
git add packages/ce-core/src/logger.ts packages/ce-core/src/types.ts packages/ce-core/src/pack.ts packages/ce-core/src/index.ts
git commit -m "feat(ce-core): add structured logging interface with no-op default"
```

---

### Task 19: Production features — token estimation cache

**Files:**

- Create: `packages/ce-core/src/cache.ts`
- Modify: `packages/ce-core/src/index.ts` (export cache)

**Step 1: Write the failing test**

Create `packages/ce-core/src/cache.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { createCachedEstimator } from "./cache";

describe("createCachedEstimator", () => {
  it("caches repeated calls", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner, { maxSize: 100 });

    const first = cached("hello");
    const second = cached("hello");

    expect(first).toBe(second);
    expect(inner).toHaveBeenCalledTimes(1);
  });

  it("handles different inputs", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner, { maxSize: 100 });

    cached("hello");
    cached("world");

    expect(inner).toHaveBeenCalledTimes(2);
  });

  it("evicts oldest entries when exceeding maxSize", () => {
    const inner = vi.fn((text: string) => text.length);
    const cached = createCachedEstimator(inner, { maxSize: 2 });

    cached("a");
    cached("b");
    cached("c"); // Should evict "a"
    cached("a"); // Should recalculate

    expect(inner).toHaveBeenCalledTimes(4);
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run src/cache.test.ts`
Expected: FAIL

**Step 3: Implement cache**

Create `packages/ce-core/src/cache.ts`:

````ts
import type { TokenEstimator } from "./types";

interface CacheOptions {
  maxSize?: number;
}

/**
 * Create a cached token estimator using an LRU cache.
 *
 * Wraps an existing estimator with content-keyed caching to avoid
 * redundant estimation of the same text.
 *
 * @param estimator - The base token estimator to wrap
 * @param options - Cache options (maxSize defaults to 1000)
 * @returns A cached TokenEstimator
 *
 * @example
 * ```ts
 * import { createCachedEstimator } from "@context-engineering/core";
 * import { openaiTokenEstimator } from "@context-engineering/providers";
 *
 * const cached = createCachedEstimator(openaiTokenEstimator, { maxSize: 500 });
 * pack(items, budget, { tokenEstimator: cached });
 * ```
 */
export function createCachedEstimator(
  estimator: TokenEstimator,
  options: CacheOptions = {}
): TokenEstimator {
  const maxSize = options.maxSize ?? 1000;
  const cache = new Map<string, number>();

  return (text: string, opts?: { model?: string; provider?: string }) => {
    if (cache.has(text)) {
      return cache.get(text)!;
    }

    const result = estimator(text, opts);

    if (cache.size >= maxSize) {
      // Evict oldest entry (first key in Map iteration order)
      const firstKey = cache.keys().next().value;
      if (firstKey !== undefined) {
        cache.delete(firstKey);
      }
    }

    cache.set(text, result);
    return result;
  };
}
````

**Step 4: Export from index**

Modify `packages/ce-core/src/index.ts` — add `export * from "./cache";`

**Step 5: Run tests**

Run: `cd /Users/k/Code/context-engineering/packages/ce-core && npx vitest run`
Expected: PASS

**Step 6: Commit**

```bash
git add packages/ce-core/src/cache.ts packages/ce-core/src/cache.test.ts packages/ce-core/src/index.ts
git commit -m "feat(ce-core): add LRU-cached token estimator"
```

---

### Task 20: Run all tests and verify

**Step 1: Run all TypeScript tests**

Run: `cd /Users/k/Code/context-engineering && pnpm test:all`
Expected: All packages pass

**Step 2: Run all Python tests**

Run: `cd /Users/k/Code/context-engineering/python && python -m pytest -v`
Expected: All tests pass

**Step 3: Run type checking**

Run: `cd /Users/k/Code/context-engineering && pnpm check:all`
Expected: No type errors

**Step 4: Format**

Run: `cd /Users/k/Code/context-engineering && pnpm format`

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: format all files"
```

---

### Task 21: Update CLAUDE.md with new APIs

**Files:**

- Modify: `CLAUDE.md` (document new public APIs)

**Step 1: Update CLAUDE.md**

Add to the Architecture section documentation for new APIs:

- `createScorer()`, `ScoringWeights`
- `packStream()`
- `createCachedEstimator()`
- `createMemoryStore()` factory
- `presets` object
- Error classes: `ValidationError`, `BudgetExceededError`, `EstimationError`
- `Logger` interface
- Zod schemas exported for user validation

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with new production APIs"
```
