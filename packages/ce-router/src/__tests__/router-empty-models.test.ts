import { describe, it, expect } from "vitest";
import { createContextRouter } from "../router.js";
import type { RouterConfig } from "../types.js";

describe("createContextRouter with an empty models config", () => {
  it("throws a clear config error instead of crashing at route time", () => {
    const config: RouterConfig = { models: [] };

    expect(() => createContextRouter(config)).toThrow(
      "RouterConfig.models must contain at least one model"
    );
  });

  it("throws even when a defaultModel is set but no models exist", () => {
    const config: RouterConfig = { models: [], defaultModel: "gpt-4.1" };

    expect(() => createContextRouter(config)).toThrow(
      "RouterConfig.models must contain at least one model"
    );
  });
});
