import type { ContextPack } from "@context-engineering/core";

interface TokenBudgetBarProps {
  pack: ContextPack;
  label?: string;
}

export function TokenBudgetBar({ pack, label }: TokenBudgetBarProps) {
  const used = pack.totalTokens;
  const budget = pack.budget.maxTokens;
  const utilization = budget > 0 ? (used / budget) * 100 : 0;
  const droppedTokens = pack.dropped.reduce(
    (sum, item) => sum + (item.tokens ?? 0),
    0
  );

  // Color thresholds
  const barColor =
    utilization > 90
      ? "bg-marker-red"
      : utilization > 70
        ? "bg-highlight-yellow"
        : "bg-marker-green";

  return (
    <div className="space-y-2">
      {label && (
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            {label}
          </span>
          <span className="text-[10px] font-mono text-muted-foreground">
            {used.toLocaleString()} / {budget.toLocaleString()} tokens
          </span>
        </div>
      )}

      {/* Main bar */}
      <div className="relative h-8 bg-marker-black/5 rounded border-2 border-marker-black/10 overflow-hidden">
        <div
          className={`absolute inset-y-0 left-0 ${barColor} transition-all duration-300`}
          style={{ width: `${Math.min(100, utilization)}%` }}
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-xs font-mono font-bold marker-black">
            {utilization.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex gap-4 text-[10px] font-mono">
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-sm bg-marker-green" />
          <span className="text-muted-foreground">
            {pack.selected.length} kept
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2.5 h-2.5 rounded-sm bg-marker-red/60" />
          <span className="text-muted-foreground">
            {pack.dropped.length} dropped ({droppedTokens.toLocaleString()}t)
          </span>
        </div>
        {pack.budget.reserveTokens ? (
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-sm bg-marker-blue/40" />
            <span className="text-muted-foreground">
              {pack.budget.reserveTokens.toLocaleString()}t reserved
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
