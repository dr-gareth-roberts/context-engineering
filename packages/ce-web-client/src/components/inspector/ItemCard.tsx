import type { ContextItem } from "@context-engineering/core";

interface ItemCardProps {
  item: ContextItem;
  variant?: "selected" | "dropped" | "neutral";
  showContent?: boolean;
}

export function ItemCard({
  item,
  variant = "neutral",
  showContent = false,
}: ItemCardProps) {
  const borderColor =
    variant === "selected"
      ? "border-marker-green/30 bg-marker-green/5"
      : variant === "dropped"
        ? "border-marker-red/30 bg-marker-red/5"
        : "border-marker-black/10 bg-card";

  return (
    <div
      className={`border-2 rounded p-3 space-y-2 ${borderColor} transition-all`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-bold marker-black">
            {item.id}
          </span>
          {item.kind && (
            <span className="px-1.5 py-0.5 text-[9px] font-mono font-bold uppercase bg-marker-black/5 text-muted-foreground rounded">
              {item.kind}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {variant === "selected" && (
            <span className="text-[9px] font-bold uppercase marker-green">
              KEPT
            </span>
          )}
          {variant === "dropped" && (
            <span className="text-[9px] font-bold uppercase marker-red">
              DROPPED
            </span>
          )}
        </div>
      </div>

      {/* Metrics row */}
      <div className="flex flex-wrap gap-3 text-[10px] font-mono text-muted-foreground">
        {item.tokens !== undefined && (
          <span>
            tokens: <b className="marker-black">{item.tokens}</b>
          </span>
        )}
        {item.score !== undefined && (
          <span>
            score: <b className="marker-black">{item.score.toFixed(2)}</b>
          </span>
        )}
        {item.priority !== undefined && (
          <span>
            priority: <b className="marker-black">{item.priority}</b>
          </span>
        )}
        {item.recency !== undefined && (
          <span>
            recency: <b className="marker-black">{item.recency.toFixed(2)}</b>
          </span>
        )}
      </div>

      {/* Token bar (mini utilization indicator) */}
      {item.tokens !== undefined && item.tokens > 0 && (
        <div className="h-1.5 bg-marker-black/5 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${
              variant === "selected" ? "bg-marker-green/60" : "bg-marker-red/40"
            }`}
            style={{
              width: `${Math.min(100, (item.tokens / 200) * 100)}%`,
            }}
          />
        </div>
      )}

      {/* Content preview */}
      {showContent && (
        <div className="mt-2 p-2 bg-marker-black/[0.02] rounded border border-marker-black/5">
          <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap break-words leading-relaxed max-h-24 overflow-y-auto">
            {item.content.length > 300
              ? item.content.slice(0, 300) + "..."
              : item.content}
          </pre>
        </div>
      )}

      {/* Compressions indicator */}
      {item.compressions && item.compressions.length > 0 && (
        <div className="flex items-center gap-1.5 text-[9px] font-mono marker-blue">
          <span className="w-3 h-3 rounded-full bg-marker-blue/20 flex items-center justify-center text-[8px]">
            ~
          </span>
          {item.compressions.length} compression
          {item.compressions.length > 1 ? "s" : ""} available
        </div>
      )}
    </div>
  );
}
