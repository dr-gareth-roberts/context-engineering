import { describe, expect, it } from "vitest";
import {
  ContextItemSchema,
  BudgetSchema,
  CompressionSchema,
} from "./schemas";

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
      compressions: [
        { content: "Short", tokens: 5, note: "summary" },
      ],
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
