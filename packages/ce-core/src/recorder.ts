import type { ContextItem, Budget, ContextPack, PackOptions } from "./types.js";
import type {
  ContextRecording,
  SerializablePackOptions,
} from "./replay-types.js";

let recordingCounter = 0;

function generateId(): string {
  return `rec-${Date.now()}-${++recordingCounter}`;
}

/** Extract only the JSON-serializable fields from PackOptions. */
function serializeOptions(options?: PackOptions): SerializablePackOptions {
  return {
    allowCompression: options?.allowCompression,
    weights: options?.weights,
    query:
      typeof options?.query === "string"
        ? options.query
        : typeof options?.query === "object" && options.query !== null
          ? options.query.text
          : undefined,
  };
}

/**
 * Records context packing decisions for later replay and analysis.
 *
 * @example
 * ```ts
 * const recorder = createContextRecorder();
 *
 * // Record a pack call
 * recorder.record({
 *   model: 'gpt-4o',
 *   items,
 *   budget: { maxTokens: 4096 },
 *   options: { weights: { priority: 1, recency: 0.7 } },
 *   result: packResult,
 * });
 *
 * // Save to JSON
 * const json = recorder.save();
 *
 * // Load from JSON
 * const recorder2 = createContextRecorder();
 * recorder2.load(json);
 * ```
 */
export function createContextRecorder() {
  const recordings: ContextRecording[] = [];

  return {
    /**
     * Record a context packing event.
     */
    record(params: {
      model: string;
      items: ContextItem[];
      budget: Budget;
      options?: PackOptions;
      result: ContextPack;
      response?: string;
      qualityScore?: number;
      metadata?: Record<string, unknown>;
    }): ContextRecording {
      const recording: ContextRecording = {
        id: generateId(),
        timestamp: new Date().toISOString(),
        model: params.model,
        items: params.items,
        budget: params.budget,
        options: serializeOptions(params.options),
        result: params.result,
        response: params.response,
        qualityScore: params.qualityScore,
        metadata: params.metadata,
      };

      recordings.push(recording);
      return recording;
    },

    /**
     * Get all recordings.
     */
    getRecordings(): readonly ContextRecording[] {
      return recordings;
    },

    /**
     * Get a specific recording by ID.
     */
    getRecording(id: string): ContextRecording | undefined {
      return recordings.find(r => r.id === id);
    },

    /**
     * Clear all recordings.
     */
    clear(): void {
      recordings.length = 0;
    },

    /**
     * Number of recordings stored.
     */
    get size(): number {
      return recordings.length;
    },

    /**
     * Serialize all recordings to a JSON string.
     */
    save(): string {
      return JSON.stringify(recordings, null, 2);
    },

    /**
     * Load recordings from a JSON string (appends to existing).
     */
    load(json: string): void {
      const parsed: unknown = JSON.parse(json);
      if (!Array.isArray(parsed)) {
        throw new Error("Expected a JSON array of recordings");
      }
      for (const item of parsed) {
        if (
          typeof item === "object" &&
          item !== null &&
          "id" in item &&
          "items" in item
        ) {
          recordings.push(item as ContextRecording);
        }
      }
    },

    /**
     * Attach a quality score to a recording (e.g. from user feedback).
     */
    scoreRecording(id: string, qualityScore: number): boolean {
      const recording = recordings.find(r => r.id === id);
      if (!recording) return false;
      recording.qualityScore = qualityScore;
      return true;
    },
  };
}

export type ContextRecorder = ReturnType<typeof createContextRecorder>;
