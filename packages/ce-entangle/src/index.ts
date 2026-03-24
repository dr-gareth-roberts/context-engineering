export { createEntanglementMesh } from "./mesh.js";
export { createAgentHandle } from "./agent-handle.js";
export {
  filterForAgent,
  isExpired,
  matchesScope,
  matchesKindFilter,
} from "./propagation.js";
export type {
  PropagationPolicy,
  EntangledItem,
  AgentRegistration,
  AgentHandle,
  EntangleOptions,
  MeshConfig,
  MeshState,
  MeshStats,
  EntanglementMesh,
} from "./types.js";
export type { MeshStore } from "./agent-handle.js";
