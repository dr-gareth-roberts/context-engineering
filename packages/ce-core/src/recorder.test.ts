import { describe, it, expect } from "vitest";
import { createContextRecorder } from "./recorder.js";
import type { ContextItem, ContextPack, Budget } from "./types.js";

function makeItems(): ContextItem[] {
  return [
    { id: "a", content: "Hello world", priority: 10, tokens: 5 },
    { id: "b", content: "Context engineering", priority: 5, tokens: 8 },
  ];
}

function makePack(items: ContextItem[], budget: Budget): ContextPack {
  return {
    budget,
    selected: [items[0]],
    dropped: [items[1]],
    totalTokens: 5,
  };
}

describe("createContextRecorder", () => {
  it("records a packing event", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    const recording = recorder.record({
      model: "gpt-4o",
      items,
      budget,
      result,
    });

    expect(recording.id).toMatch(/^rec-/);
    expect(recording.model).toBe("gpt-4o");
    expect(recording.items).toBe(items);
    expect(recording.result).toBe(result);
    expect(recorder.size).toBe(1);
  });

  it("stores multiple recordings", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    recorder.record({ model: "gpt-4o", items, budget, result });
    recorder.record({ model: "claude-sonnet-4-6", items, budget, result });

    expect(recorder.size).toBe(2);
    expect(recorder.getRecordings()).toHaveLength(2);
  });

  it("retrieves a recording by ID", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    const recording = recorder.record({ model: "gpt-4o", items, budget, result });
    expect(recorder.getRecording(recording.id)).toBe(recording);
    expect(recorder.getRecording("nonexistent")).toBeUndefined();
  });

  it("clears all recordings", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    recorder.record({ model: "gpt-4o", items, budget, result });
    recorder.clear();

    expect(recorder.size).toBe(0);
    expect(recorder.getRecordings()).toHaveLength(0);
  });

  it("saves and loads recordings as JSON", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    recorder.record({ model: "gpt-4o", items, budget, result });
    const json = recorder.save();

    const recorder2 = createContextRecorder();
    recorder2.load(json);

    expect(recorder2.size).toBe(1);
    const loaded = recorder2.getRecordings()[0];
    expect(loaded.model).toBe("gpt-4o");
    expect(loaded.items).toHaveLength(2);
  });

  it("throws on invalid JSON load", () => {
    const recorder = createContextRecorder();
    expect(() => recorder.load("not json")).toThrow();
    expect(() => recorder.load('{"not": "array"}')).toThrow("Expected a JSON array");
  });

  it("scores a recording by ID", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    const recording = recorder.record({ model: "gpt-4o", items, budget, result });

    expect(recorder.scoreRecording(recording.id, 0.85)).toBe(true);
    expect(recorder.getRecording(recording.id)?.qualityScore).toBe(0.85);
    expect(recorder.scoreRecording("nonexistent", 0.5)).toBe(false);
  });

  it("records optional response and metadata", () => {
    const recorder = createContextRecorder();
    const items = makeItems();
    const budget = { maxTokens: 10 };
    const result = makePack(items, budget);

    const recording = recorder.record({
      model: "gpt-4o",
      items,
      budget,
      result,
      response: "Here is my answer...",
      qualityScore: 0.9,
      metadata: { promptVersion: "v2" },
    });

    expect(recording.response).toBe("Here is my answer...");
    expect(recording.qualityScore).toBe(0.9);
    expect(recording.metadata?.promptVersion).toBe("v2");
  });
});
