import type {
  Budget,
  ContextItem,
  ContextPack,
} from "@context-engineering/core";
import { analyzeContext, estimateTokens } from "@context-engineering/core";

import { generateAlerts } from "./alerts.js";
import type {
  DriftMonitorConfig,
  DriftMonitorState,
  DriftObservation,
  DriftReport,
  DriftSeverity,
} from "./types.js";

export interface DriftMonitor {
  /** Feed a new observation from a context pack. */
  observe(packed: ContextPack, budget: Budget): void;
  /** Feed a new observation from raw items and budget. */
  observeItems(items: ContextItem[], budget: Budget): void;
  /** Get the current drift report. */
  report(): DriftReport;
  /** Reset all observations and baselines. */
  reset(): void;
  /** Get the raw observation history (windowed). */
  history(): DriftObservation[];
  /** Export state for persistence. */
  exportState(): DriftMonitorState;
  /** Import previously exported state. */
  importState(state: DriftMonitorState): void;
}

/**
 * Build a DriftObservation from a list of context items and budget.
 */
function buildObservation(
  items: ContextItem[],
  budget: Budget
): DriftObservation {
  const quality = analyzeContext(items);
  const totalTokens = items.reduce(
    (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
    0
  );
  const effectiveBudget = budget.maxTokens - (budget.reserveTokens ?? 0);
  const budgetUtilization =
    effectiveBudget > 0 ? totalTokens / effectiveBudget : 0;

  const staleItemCount = items.filter(item => (item.recency ?? 0) < 0.2).length;

  const topKinds: Record<string, number> = {};
  for (const item of items) {
    const kind = item.kind ?? "unknown";
    topKinds[kind] = (topKinds[kind] ?? 0) + 1;
  }

  return {
    timestamp: Date.now(),
    quality,
    itemCount: items.length,
    totalTokens,
    budgetUtilization: Math.min(budgetUtilization, 1),
    staleItemCount,
    topKinds,
  };
}

/**
 * Create a drift monitor that tracks context quality over time.
 *
 * The monitor maintains a sliding window of observations and analyzes
 * them for drift across multiple dimensions. When drift is detected,
 * the optional `onAlert` callback is invoked.
 *
 * @param config - Optional monitor configuration
 * @returns A DriftMonitor instance
 *
 * @example
 * ```ts
 * const monitor = createDriftMonitor({
 *   windowSize: 20,
 *   onAlert: (alert) => console.warn(alert.message),
 * });
 *
 * // After each pack/compile cycle:
 * monitor.observe(packed, budget);
 * const report = monitor.report();
 * if (report.drifting) {
 *   console.log("Drift detected since", new Date(report.since!));
 * }
 * ```
 */
export function createDriftMonitor(config?: DriftMonitorConfig): DriftMonitor {
  const windowSize = config?.windowSize ?? 10;
  const minObservations = config?.minObservations ?? 3;
  const thresholds = config?.thresholds;
  const onAlert = config?.onAlert;

  let observations: DriftObservation[] = [];
  let driftSince: number | null = null;

  function addObservation(obs: DriftObservation): void {
    observations.push(obs);
    // Trim to window size for O(windowSize) memory
    if (observations.length > windowSize) {
      observations = observations.slice(observations.length - windowSize);
    }

    // Only evaluate alerts if we have enough observations
    if (observations.length >= minObservations && onAlert) {
      const { alerts } = generateAlerts(observations, thresholds);
      for (const alert of alerts) {
        onAlert(alert);
      }
    }
  }

  function buildReport(): DriftReport {
    if (observations.length === 0) {
      const emptyDim = {
        current: 0,
        baseline: 0,
        delta: 0,
        trend: "stable" as const,
        severity: "healthy" as const,
        history: [] as number[],
      };
      return {
        status: "healthy",
        drifting: false,
        since: null,
        observationCount: 0,
        dimensions: {
          relevance: { ...emptyDim },
          redundancy: { ...emptyDim },
          diversity: { ...emptyDim },
          density: { ...emptyDim },
          freshness: { ...emptyDim },
          utilization: { ...emptyDim },
        },
        alerts: [],
        recommendations: [],
      };
    }

    const { dimensions, alerts } =
      observations.length >= minObservations
        ? generateAlerts(observations, thresholds)
        : generateAlerts(observations, thresholds);

    // Suppress alerts if below minObservations
    const effectiveAlerts =
      observations.length >= minObservations ? alerts : [];

    // Determine worst severity across all dimensions
    const severityOrder: DriftSeverity[] = ["healthy", "warning", "critical"];
    let worstSeverity: DriftSeverity = "healthy";
    if (observations.length >= minObservations) {
      for (const dim of Object.values(dimensions)) {
        const idx = severityOrder.indexOf(dim.severity);
        if (idx > severityOrder.indexOf(worstSeverity)) {
          worstSeverity = dim.severity;
        }
      }
    }

    const isDrifting = worstSeverity !== "healthy";

    // Track when drift started
    if (isDrifting && driftSince === null) {
      driftSince = observations[observations.length - 1].timestamp;
    } else if (!isDrifting) {
      driftSince = null;
    }

    const recommendations = effectiveAlerts.map(a => a.recommendation);
    const uniqueRecommendations = [...new Set(recommendations)];

    return {
      status: worstSeverity,
      drifting: isDrifting,
      since: driftSince,
      observationCount: observations.length,
      dimensions,
      alerts: effectiveAlerts,
      recommendations: uniqueRecommendations,
    };
  }

  return {
    observe(packed: ContextPack, budget: Budget): void {
      const obs = buildObservation(packed.selected, budget);
      addObservation(obs);
    },

    observeItems(items: ContextItem[], budget: Budget): void {
      const obs = buildObservation(items, budget);
      addObservation(obs);
    },

    report(): DriftReport {
      return buildReport();
    },

    reset(): void {
      observations = [];
      driftSince = null;
    },

    history(): DriftObservation[] {
      return [...observations];
    },

    exportState(): DriftMonitorState {
      return {
        observations: [...observations],
        config: {
          windowSize,
          thresholds,
          minObservations,
        },
      };
    },

    importState(state: DriftMonitorState): void {
      observations = [...state.observations];
      // Trim imported observations to window size
      if (observations.length > windowSize) {
        observations = observations.slice(observations.length - windowSize);
      }

      const importedReport = buildReport();
      driftSince = importedReport.drifting
        ? (importedReport.since ?? observations[observations.length - 1]?.timestamp ?? null)
        : null;
    },
  };
}
