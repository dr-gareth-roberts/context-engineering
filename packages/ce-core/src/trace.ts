import { ContextItem, Budget, ContextTrace, PackOptions } from "./types";
import { internalPack } from "./pack";

export function tracePack(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): ContextTrace {
  const { pack, steps } = internalPack(items, budget, options, true);

  return {
    pack,
    steps: steps ?? [],
    createdAt: new Date().toISOString()
  };
}
