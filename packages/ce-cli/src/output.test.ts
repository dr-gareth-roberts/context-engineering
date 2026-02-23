import { describe, expect, it } from "vitest";
import { fmt, isJsonMode } from "./output.js";

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
