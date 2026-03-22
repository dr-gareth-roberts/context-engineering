import type { ContextItem, Budget } from "@context-engineering/core";

export interface ModelTier {
  model: string;
  maxComplexity: number; // 0-1
  costPer1kInput: number;
  costPer1kOutput: number;
  maxTokens: number;
  capabilities?: string[]; // ['tool-calling', 'vision']
}

export interface RouterConfig {
  models: ModelTier[];
  defaultModel?: string;
  complexityWeights?: ComplexityWeights;
}

export interface ComplexityWeights {
  diversity?: number; // default 0.25
  density?: number; // default 0.2
  dependencyDepth?: number; // default 0.2
  toolCallCount?: number; // default 0.15
  multilinguality?: number; // default 0.1
  averageItemLength?: number; // default 0.1
}

export interface ComplexityBreakdown {
  overall: number; // 0-1
  dimensions: {
    diversity: number;
    density: number;
    dependencyDepth: number;
    toolCallCount: number;
    multilinguality: number;
    averageItemLength: number;
  };
}

export interface RoutingDecision {
  model: string;
  complexity: number;
  complexityBreakdown: ComplexityBreakdown;
  reasoning: string;
  estimatedCost: { inputCostPer1k: number; outputCostPer1k: number };
  alternativeModel?: string;
  alternativeCostDelta?: number;
}

export interface ContextRouter {
  route(
    items: ContextItem[],
    budget: Budget,
    options?: RouteOptions
  ): RoutingDecision;
}

export interface RouteOptions {
  requiredCapabilities?: string[];
}

export interface AdaptiveRouterConfig extends RouterConfig {
  minSamples?: number; // default 20
  learningRate?: number; // default 0.1
}

export interface AdaptiveRouter extends ContextRouter {
  route(
    items: ContextItem[],
    budget: Budget,
    options?: RouteOptions
  ): RoutingDecision;
  reportOutcome(decision: RoutingDecision, quality: number): void;
  getInsights(): RouterInsights;
}

export interface RouterInsights {
  totalDecisions: number;
  modelStats: Record<
    string,
    {
      uses: number;
      avgQuality: number;
      avgComplexity: number;
    }
  >;
  potentialSavings: number;
}

export interface FallbackConfig {
  qualityThreshold: number;
  qualityCallback: (response: string) => number | Promise<number>;
  maxRetries?: number; // default 1
}

export interface FallbackResult {
  decision: RoutingDecision;
  finalModel: string;
  attempts: number;
  fellBack: boolean;
}
