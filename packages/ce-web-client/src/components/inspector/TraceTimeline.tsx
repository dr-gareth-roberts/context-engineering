import type { TraceStep } from "@context-engineering/core";

interface TraceTimelineProps {
  steps: TraceStep[];
  onStepClick?: (step: TraceStep) => void;
  selectedStepId?: string;
}

const decisionConfig = {
  include: {
    color: "bg-marker-green",
    border: "border-marker-green/30",
    bg: "bg-marker-green/5",
    label: "INCLUDED",
    icon: "+",
  },
  exclude: {
    color: "bg-marker-red",
    border: "border-marker-red/30",
    bg: "bg-marker-red/5",
    label: "EXCLUDED",
    icon: "-",
  },
  compress: {
    color: "bg-marker-blue",
    border: "border-marker-blue/30",
    bg: "bg-marker-blue/5",
    label: "COMPRESSED",
    icon: "~",
  },
} as const;

export function TraceTimeline({
  steps,
  onStepClick,
  selectedStepId,
}: TraceTimelineProps) {
  if (steps.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground text-sm italic">
        No trace steps. Enable tracing to see decisions.
      </div>
    );
  }

  // Running token counter
  let runningTokens = 0;

  return (
    <div className="space-y-1">
      {steps.map((step, i) => {
        const config = decisionConfig[step.decision];
        const isSelected = step.id === selectedStepId;

        if (step.decision === "include" || step.decision === "compress") {
          runningTokens += step.tokens ?? 0;
        }

        return (
          <button
            key={`${step.id}-${i}`}
            type="button"
            onClick={() => onStepClick?.(step)}
            className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded border-2 transition-all
              ${config.bg} ${config.border}
              ${isSelected ? "ring-2 ring-marker-blue shadow-md" : "hover:shadow-sm"}
            `}
          >
            {/* Decision icon */}
            <div
              className={`w-6 h-6 rounded-full ${config.color} flex items-center justify-center text-white text-xs font-mono font-bold shrink-0`}
            >
              {config.icon}
            </div>

            {/* Timeline line */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs font-bold marker-black truncate">
                  {step.id}
                </span>
                <span
                  className={`text-[9px] font-bold uppercase tracking-wider ${
                    step.decision === "include"
                      ? "marker-green"
                      : step.decision === "exclude"
                        ? "marker-red"
                        : "marker-blue"
                  }`}
                >
                  {config.label}
                </span>
              </div>

              <div className="flex items-center gap-3 mt-0.5">
                {step.score !== undefined && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    score: {step.score.toFixed(2)}
                  </span>
                )}
                {step.tokens !== undefined && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {step.tokens}t
                  </span>
                )}
                {step.decision !== "exclude" && (
                  <span className="text-[10px] text-muted-foreground font-mono">
                    cumulative: {runningTokens}t
                  </span>
                )}
                {step.reason && (
                  <span className="text-[10px] text-muted-foreground italic truncate">
                    {step.reason}
                  </span>
                )}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
