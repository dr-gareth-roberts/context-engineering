import { describe, it, expect, vi, beforeEach } from "vitest";
import { logSummary, emitEvent } from "./logger.js";
import type { ContextEvent, ResolvedConfig } from "./types.js";
import { resolveConfig } from "./types.js";

function makeEvent(overrides: Partial<ContextEvent> = {}): ContextEvent {
  return {
    timestamp: Date.now(),
    model: "gpt-4o",
    totalMessages: 34,
    keptMessages: 12,
    trimmedMessages: 22,
    summarized: false,
    tokensUsed: 2847,
    tokenBudget: 4096,
    utilization: 69.5,
    packTimeMs: 5,
    ...overrides,
  };
}

describe("logSummary", () => {
  it("logs a formatted summary to console", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    logSummary(makeEvent());

    expect(spy).toHaveBeenCalledOnce();
    const output = spy.mock.calls[0][0] as string;
    expect(output).toContain("[context-engineering]");
    expect(output).toContain("12/34 messages kept");
    expect(output).toContain("69.5%");
    expect(output).toContain("22 trimmed");
    spy.mockRestore();
  });

  it("includes summary injection note when summarized", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    logSummary(makeEvent({ summarized: true }));

    const output = spy.mock.calls[0][0] as string;
    expect(output).toContain("summary injected");
    spy.mockRestore();
  });

  it("omits trimmed count when nothing was trimmed", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    logSummary(makeEvent({ trimmedMessages: 0 }));

    const output = spy.mock.calls[0][0] as string;
    expect(output).not.toContain("trimmed");
    spy.mockRestore();
  });
});

describe("emitEvent", () => {
  it("calls pack listener on every event", () => {
    const packListener = vi.fn();
    const config = resolveConfig({ log: false, on: { pack: packListener } });
    const event = makeEvent();

    emitEvent(config, event);
    expect(packListener).toHaveBeenCalledWith(event);
  });

  it("calls trim listener only when messages were trimmed", () => {
    const trimListener = vi.fn();
    const config = resolveConfig({ log: false, on: { trim: trimListener } });

    emitEvent(config, makeEvent({ trimmedMessages: 5 }));
    expect(trimListener).toHaveBeenCalledOnce();

    trimListener.mockClear();
    emitEvent(config, makeEvent({ trimmedMessages: 0 }));
    expect(trimListener).not.toHaveBeenCalled();
  });

  it("logs to console when log is true", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    const config = resolveConfig({ log: true });

    emitEvent(config, makeEvent());
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });

  it("does not log when log is false", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    const config = resolveConfig({ log: false });

    emitEvent(config, makeEvent());
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
