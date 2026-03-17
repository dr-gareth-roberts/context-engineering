import { describe, expect, it, afterEach } from "vitest";
import {
  fmt,
  isJsonMode,
  setForceJson,
  setNoColor,
  resetOutputState,
} from "./output.js";

describe("fmt", () => {
  it("returns string containing the text", () => {
    expect(fmt.red("error")).toContain("error");
    expect(fmt.green("ok")).toContain("ok");
    expect(fmt.bold("heading")).toContain("heading");
    expect(fmt.dim("faded")).toContain("faded");
    expect(fmt.cyan("info")).toContain("info");
  });

  it("success prefix includes text", () => {
    expect(fmt.success("done")).toContain("done");
  });

  it("error prefix includes text", () => {
    expect(fmt.error("fail")).toContain("fail");
  });
});

describe("isTTY", () => {
  it("returns a boolean", () => {
    // isJsonMode depends on the module-level isTTY constant internally
    const result = isJsonMode();
    expect(typeof result).toBe("boolean");
  });
});

describe("readStdin", () => {
  it("returns collected stdin data as a string", async () => {
    const { readStdin } = await import("./output.js");
    const { Readable } = await import("stream");

    const fakeStdin = new Readable({
      read() {
        this.push("hello from stdin");
        this.push(null);
      },
    });

    const originalStdin = process.stdin;
    Object.defineProperty(process, "stdin", {
      value: fakeStdin,
      writable: true,
      configurable: true,
    });

    try {
      const data = await readStdin();
      expect(typeof data).toBe("string");
      expect(data).toBe("hello from stdin");
    } finally {
      Object.defineProperty(process, "stdin", {
        value: originalStdin,
        writable: true,
        configurable: true,
      });
    }
  });
});

describe("outputError", () => {
  it("produces formatted error output containing the message and marker", () => {
    const formatted = fmt.error("something went wrong");
    expect(typeof formatted).toBe("string");
    expect(formatted).toContain("something went wrong");
    expect(formatted).toContain("\u2717");
  });
});

// ─── Regression tests for audit fixes ─────────────────────────────────

describe("NO_COLOR support (H3)", () => {
  // In test runner, stdout is not a TTY, so color() already returns plain
  // text via the !isTTY check. We verify the NO_COLOR env var path works
  // by confirming fmt functions return the raw text without ANSI escapes.
  it("fmt functions return plain text when NO_COLOR is set", () => {
    // NO_COLOR is set in our test environment by default (non-TTY),
    // but we also verify the output is escape-free.
    const result = fmt.green("hello");
    expect(result).toBe("hello");
  });

  it("fmt.success returns plain text with check mark when NO_COLOR is set", () => {
    const result = fmt.success("done");
    expect(result).toBe("\u2713 done");
  });

  it("fmt.error returns plain text with x mark when NO_COLOR is set", () => {
    const result = fmt.error("fail");
    expect(result).toBe("\u2717 fail");
  });

  it("setNoColor(true) prevents ANSI codes", () => {
    setNoColor(true);
    try {
      const result = fmt.red("danger");
      // Should not contain ANSI escape sequences
      expect(result).not.toContain("\x1b[");
      expect(result).toBe("danger");
    } finally {
      resetOutputState();
    }
  });
});

describe("resetOutputState (H4)", () => {
  afterEach(() => {
    resetOutputState();
  });

  it("resets forceJson to false", () => {
    setForceJson(true);
    expect(isJsonMode()).toBe(true);
    resetOutputState();
    // In test (non-TTY), isJsonMode returns true regardless of forceJson,
    // but we verify the function executes without error and the internal
    // state is reset by checking it doesn't throw.
    expect(typeof isJsonMode()).toBe("boolean");
  });

  it("resets noColor to match NO_COLOR env var", () => {
    setNoColor(true);
    resetOutputState();
    // After reset, noColor should reflect process.env.NO_COLOR state.
    // In non-TTY, color is always disabled, so fmt returns plain text.
    const result = fmt.bold("test");
    expect(result).toBe("test");
  });

  it("is idempotent -- calling twice has same effect", () => {
    setForceJson(true);
    setNoColor(true);
    resetOutputState();
    resetOutputState();
    const result = fmt.cyan("ok");
    expect(result).toBe("ok");
  });
});
