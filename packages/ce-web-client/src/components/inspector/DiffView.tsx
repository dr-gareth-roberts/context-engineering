import type { PackDiff } from "@context-engineering/core";
import { ItemCard } from "./ItemCard";

interface DiffViewProps {
  diff: PackDiff;
}

export function DiffView({ diff }: DiffViewProps) {
  const hasChanges =
    diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0;

  return (
    <div className="space-y-4">
      {/* Summary badges */}
      <div className="flex flex-wrap gap-2">
        {diff.added.length > 0 && (
          <span className="px-2 py-1 text-[10px] font-mono font-bold bg-marker-green/10 marker-green rounded border border-marker-green/20">
            +{diff.added.length} added
          </span>
        )}
        {diff.removed.length > 0 && (
          <span className="px-2 py-1 text-[10px] font-mono font-bold bg-marker-red/10 marker-red rounded border border-marker-red/20">
            -{diff.removed.length} removed
          </span>
        )}
        {diff.changed.length > 0 && (
          <span className="px-2 py-1 text-[10px] font-mono font-bold bg-marker-blue/10 marker-blue rounded border border-marker-blue/20">
            ~{diff.changed.length} changed
          </span>
        )}
        <span className="px-2 py-1 text-[10px] font-mono font-bold bg-marker-black/5 text-muted-foreground rounded border border-marker-black/10">
          {diff.kept.length} kept
        </span>
      </div>

      {!hasChanges && (
        <div className="text-center py-6 text-muted-foreground text-sm italic">
          Packs are identical.
        </div>
      )}

      {/* Added items */}
      {diff.added.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold uppercase tracking-widest marker-green">
            Added in B
          </h4>
          {diff.added.map(item => (
            <ItemCard
              key={item.id}
              item={item}
              variant="selected"
              showContent
            />
          ))}
        </div>
      )}

      {/* Removed items */}
      {diff.removed.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold uppercase tracking-widest marker-red">
            Removed in B
          </h4>
          {diff.removed.map(item => (
            <ItemCard key={item.id} item={item} variant="dropped" showContent />
          ))}
        </div>
      )}

      {/* Changed items */}
      {diff.changed.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold uppercase tracking-widest marker-blue">
            Changed
          </h4>
          {diff.changed.map(({ before, after }) => (
            <div key={before.id} className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-[9px] font-bold uppercase text-muted-foreground mb-1 block">
                  Before
                </span>
                <ItemCard item={before} variant="dropped" showContent />
              </div>
              <div>
                <span className="text-[9px] font-bold uppercase text-muted-foreground mb-1 block">
                  After
                </span>
                <ItemCard item={after} variant="selected" showContent />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
