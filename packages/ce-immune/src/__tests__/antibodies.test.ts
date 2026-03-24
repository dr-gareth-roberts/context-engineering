import { describe, it, expect, beforeEach } from "vitest";
import type { ContextItem, Budget } from "@context-engineering/core";
import type { FailureRecord, Fingerprint } from "../types.js";
import {
  createAntibody,
  matchAntibody,
  resetIdCounter,
} from "../antibodies.js";
import { extractFingerprint } from "../fingerprint.js";

function makeItem(
  overrides: Partial<ContextItem> & { id: string; content: string }
): ContextItem {
  return {
    id: overrides.id,
    content: overrides.content,
    kind: overrides.kind,
    priority: overrides.priority,
    recency: overrides.recency,
    tokens: overrides.tokens,
    ...overrides,
  } as ContextItem;
}

const DEFAULT_BUDGET: Budget = { maxTokens: 4000 };

function makeFailureRecord(overrides?: Partial<FailureRecord>): FailureRecord {
  return {
    items: [
      makeItem({
        id: "1",
        content: "system prompt",
        kind: "system",
        priority: 1.0,
        recency: 1.0,
      }),
      makeItem({
        id: "2",
        content: "old stale data from last year",
        kind: "retrieval",
        priority: 0.3,
        recency: 0.05,
      }),
      makeItem({
        id: "3",
        content: "old stale data from last year duplicated",
        kind: "retrieval",
        priority: 0.2,
        recency: 0.1,
      }),
    ],
    budget: DEFAULT_BUDGET,
    symptom: "Hallucinated outdated facts",
    diagnosis: "Too many stale retrieval items dominated the context",
    ...overrides,
  };
}

beforeEach(() => {
  resetIdCounter();
});

describe("createAntibody", () => {
  it("creates an antibody with correct fields", () => {
    const record = makeFailureRecord();
    const antibody = createAntibody(record);

    expect(antibody.id).toBe("ab-1");
    expect(antibody.symptom).toBe("Hallucinated outdated facts");
    expect(antibody.diagnosis).toBe(
      "Too many stale retrieval items dominated the context"
    );
    expect(antibody.severity).toBe("warning");
    expect(antibody.matchThreshold).toBe(0.7);
    expect(antibody.pattern).toBeDefined();
    expect(antibody.pattern.itemCount).toBe(3);
    expect(antibody.createdAt).toBeGreaterThan(0);
  });

  it("uses custom threshold when provided", () => {
    const record = makeFailureRecord();
    const antibody = createAntibody(record, 0.9);
    expect(antibody.matchThreshold).toBe(0.9);
  });

  it("defaults diagnosis to 'Unknown cause' when not provided", () => {
    const record = makeFailureRecord({ diagnosis: undefined });
    const antibody = createAntibody(record);
    expect(antibody.diagnosis).toBe("Unknown cause");
  });

  it("uses severity from failure record", () => {
    const record = makeFailureRecord({ severity: "block" });
    const antibody = createAntibody(record);
    expect(antibody.severity).toBe("block");
  });

  it("generates incrementing IDs", () => {
    const record = makeFailureRecord();
    const ab1 = createAntibody(record);
    const ab2 = createAntibody(record);
    expect(ab1.id).toBe("ab-1");
    expect(ab2.id).toBe("ab-2");
  });

  it("extracts fingerprint from failure items", () => {
    const record = makeFailureRecord();
    const antibody = createAntibody(record);
    expect(antibody.pattern.kindsPresent).toContain("system");
    expect(antibody.pattern.kindsPresent).toContain("retrieval");
    expect(antibody.pattern.stalenessRatio).toBeGreaterThan(0);
  });
});

describe("matchAntibody", () => {
  it("matches identical fingerprint", () => {
    const record = makeFailureRecord();
    const antibody = createAntibody(record, 0.7);
    const fingerprint = extractFingerprint(record.items, record.budget);
    const result = matchAntibody(antibody, fingerprint);
    expect(result.matches).toBe(true);
    expect(result.similarity).toBeCloseTo(1.0);
  });

  it("does not match very different fingerprint", () => {
    const record = makeFailureRecord();
    const antibody = createAntibody(record, 0.7);

    const differentItems = [
      makeItem({
        id: "x",
        content: "completely unique new content here",
        kind: "conversation",
        priority: 0.9,
        recency: 0.95,
      }),
    ];
    const differentFp = extractFingerprint(differentItems, { maxTokens: 100 });
    const result = matchAntibody(antibody, differentFp);
    expect(result.similarity).toBeLessThan(0.7);
    expect(result.matches).toBe(false);
  });

  it("respects custom threshold", () => {
    const record = makeFailureRecord();
    // Very high threshold means even similar fingerprints won't match
    const antibody = createAntibody(record, 0.99);
    const slightlyDifferentItems = [
      makeItem({
        id: "1",
        content: "system prompt",
        kind: "system",
        priority: 1.0,
        recency: 1.0,
      }),
      makeItem({
        id: "2",
        content: "old stale data from last year",
        kind: "retrieval",
        priority: 0.3,
        recency: 0.05,
      }),
      makeItem({
        id: "3",
        content: "old stale data from last year duplicated",
        kind: "retrieval",
        priority: 0.2,
        recency: 0.1,
      }),
      makeItem({
        id: "4",
        content: "an extra item that shifts things",
        kind: "code",
        priority: 0.5,
        recency: 0.5,
      }),
    ];
    const fp = extractFingerprint(slightlyDifferentItems, DEFAULT_BUDGET);
    const result = matchAntibody(antibody, fp);
    expect(result.matches).toBe(false);
  });
});
