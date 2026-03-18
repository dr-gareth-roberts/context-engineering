import { describe, expect, it } from "vitest";
import {
  ContextItemSchema,
  BudgetSchema,
  CompressionSchema,
  KindAllocationSchema,
  CacheConfigSchema,
  PlacementOptionsSchema,
  CompactionOptionsSchema,
  validateWithSchema,
} from "./schemas.js";
import { ValidationError } from "./errors.js";
import { packWithAllocation } from "./allocation.js";
import { packWithCacheTopology } from "./cache-topology.js";
import { placeItems } from "./placement.js";
import { createContextManager } from "./compaction.js";

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

describe("KindAllocationSchema", () => {
  it("accepts valid allocation config", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "code",
        targetRatio: 0.5,
      })
    ).not.toThrow();
  });

  it("accepts full allocation config with all fields", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "system",
        targetRatio: 0.15,
        minTokens: 500,
        maxTokens: 1500,
        priority: 10,
      })
    ).not.toThrow();
  });

  it("rejects empty kind", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "",
        targetRatio: 0.5,
      })
    ).toThrow();
  });

  it("rejects targetRatio > 1", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "code",
        targetRatio: 1.5,
      })
    ).toThrow();
  });

  it("rejects negative targetRatio", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "code",
        targetRatio: -0.1,
      })
    ).toThrow();
  });

  it("rejects negative minTokens", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "code",
        minTokens: -100,
      })
    ).toThrow();
  });

  it("rejects zero maxTokens", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "code",
        maxTokens: 0,
      })
    ).toThrow();
  });

  it("rejects negative priority", () => {
    expect(() =>
      KindAllocationSchema.parse({
        kind: "code",
        priority: -1,
      })
    ).toThrow();
  });
});

describe("CacheConfigSchema", () => {
  it("accepts empty config", () => {
    expect(() => CacheConfigSchema.parse({})).not.toThrow();
  });

  it("accepts valid provider values", () => {
    for (const provider of ["anthropic", "openai", "auto"]) {
      expect(() => CacheConfigSchema.parse({ provider })).not.toThrow();
    }
  });

  it("rejects invalid provider", () => {
    expect(() => CacheConfigSchema.parse({ provider: "google" })).toThrow();
  });

  it("accepts valid minPrefixTokens", () => {
    expect(() =>
      CacheConfigSchema.parse({ minPrefixTokens: 1024 })
    ).not.toThrow();
  });

  it("rejects negative minPrefixTokens", () => {
    expect(() => CacheConfigSchema.parse({ minPrefixTokens: -1 })).toThrow();
  });

  it("accepts markBreakpoints boolean", () => {
    expect(() =>
      CacheConfigSchema.parse({ markBreakpoints: true })
    ).not.toThrow();
  });
});

describe("PlacementOptionsSchema", () => {
  it("accepts empty options", () => {
    expect(() => PlacementOptionsSchema.parse({})).not.toThrow();
  });

  it("accepts valid strategy score-order", () => {
    expect(() =>
      PlacementOptionsSchema.parse({ strategy: "score-order" })
    ).not.toThrow();
  });

  it("accepts valid strategy attention-optimized", () => {
    expect(() =>
      PlacementOptionsSchema.parse({ strategy: "attention-optimized" })
    ).not.toThrow();
  });

  it("rejects invalid strategy", () => {
    expect(() =>
      PlacementOptionsSchema.parse({ strategy: "invalid" })
    ).toThrow();
  });

  it("accepts model string", () => {
    expect(() =>
      PlacementOptionsSchema.parse({ model: "claude" })
    ).not.toThrow();
  });
});

describe("CompactionOptionsSchema", () => {
  it("accepts valid options with budget only", () => {
    expect(() =>
      CompactionOptionsSchema.parse({
        budget: { maxTokens: 8000 },
      })
    ).not.toThrow();
  });

  it("accepts full valid options", () => {
    expect(() =>
      CompactionOptionsSchema.parse({
        budget: { maxTokens: 8000, reserveTokens: 500 },
        summarizeAfterTurns: 3,
        preserveRecentTurns: 2,
        systemPrompt: "You are a helpful assistant.",
      })
    ).not.toThrow();
  });

  it("rejects missing budget", () => {
    expect(() =>
      CompactionOptionsSchema.parse({
        summarizeAfterTurns: 3,
      })
    ).toThrow();
  });

  it("rejects invalid budget", () => {
    expect(() =>
      CompactionOptionsSchema.parse({
        budget: { maxTokens: -1 },
      })
    ).toThrow();
  });

  it("rejects zero summarizeAfterTurns", () => {
    expect(() =>
      CompactionOptionsSchema.parse({
        budget: { maxTokens: 8000 },
        summarizeAfterTurns: 0,
      })
    ).toThrow();
  });

  it("rejects negative preserveRecentTurns", () => {
    expect(() =>
      CompactionOptionsSchema.parse({
        budget: { maxTokens: 8000 },
        preserveRecentTurns: -1,
      })
    ).toThrow();
  });
});

describe("validateWithSchema", () => {
  it("returns parsed data on success", () => {
    const result = validateWithSchema(
      BudgetSchema,
      { maxTokens: 4096 },
      "budget"
    );
    expect(result).toEqual({ maxTokens: 4096 });
  });

  it("throws ValidationError with details on failure", () => {
    try {
      validateWithSchema(BudgetSchema, { maxTokens: -1 }, "budget");
      expect.fail("should have thrown");
    } catch (e) {
      expect(e).toBeInstanceOf(ValidationError);
      const err = e as ValidationError;
      expect(err.message).toContain("Invalid budget");
      expect(err.details.length).toBeGreaterThan(0);
      expect(err.details[0].path).toBe("maxTokens");
    }
  });
});

describe("extended feature validation", () => {
  it("packWithAllocation rejects invalid allocation config with empty kind", () => {
    expect(() =>
      packWithAllocation(
        [{ id: "a", content: "hello", kind: "code" }],
        { maxTokens: 1000 },
        [{ kind: "", targetRatio: 0.5 }]
      )
    ).toThrow(ValidationError);
  });

  it("packWithAllocation rejects targetRatio > 1", () => {
    expect(() =>
      packWithAllocation(
        [{ id: "a", content: "hello", kind: "code" }],
        { maxTokens: 1000 },
        [{ kind: "code", targetRatio: 1.5 }]
      )
    ).toThrow(ValidationError);
  });

  it("packWithCacheTopology rejects invalid provider", () => {
    expect(() =>
      packWithCacheTopology(
        [{ id: "a", content: "hello" }],
        { maxTokens: 1000 },
        {},
        { provider: "google" as any }
      )
    ).toThrow(ValidationError);
  });

  it("placeItems rejects invalid strategy", () => {
    expect(() => placeItems([], { strategy: "invalid" as any })).toThrow(
      ValidationError
    );
  });

  it("createContextManager rejects invalid budget", () => {
    expect(() =>
      createContextManager({
        budget: { maxTokens: -1 },
      })
    ).toThrow(ValidationError);
  });

  it("createContextManager rejects zero summarizeAfterTurns", () => {
    expect(() =>
      createContextManager({
        budget: { maxTokens: 8000 },
        summarizeAfterTurns: 0,
      })
    ).toThrow(ValidationError);
  });
});
