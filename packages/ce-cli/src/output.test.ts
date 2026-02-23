import { describe, expect, it } from "vitest";
import { fmt } from "./output.js";

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
