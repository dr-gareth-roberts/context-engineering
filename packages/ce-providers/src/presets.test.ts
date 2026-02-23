import { describe, expect, it } from "vitest";
import { presets } from "./presets.js";
import {
  openaiTokenEstimator,
  anthropicTokenEstimator,
} from "./token-estimators.js";

describe("presets", () => {
  describe("presets.openai", () => {
    it("has an estimator field that is the openaiTokenEstimator", () => {
      expect(presets.openai.estimator).toBe(openaiTokenEstimator);
    });
  });

  describe("presets.anthropic", () => {
    it("has an estimator field that is the anthropicTokenEstimator", () => {
      expect(presets.anthropic.estimator).toBe(anthropicTokenEstimator);
    });
  });
});
