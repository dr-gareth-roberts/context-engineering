/**
 * Structured logging interface compatible with console, pino, winston, etc.
 *
 * @example
 * ```ts
 * import { pack } from "@context-engineering/core";
 *
 * const result = pack(items, budget, { logger: console });
 * ```
 */
export interface Logger {
  debug(message: string, data?: Record<string, unknown>): void;
  info(message: string, data?: Record<string, unknown>): void;
  warn(message: string, data?: Record<string, unknown>): void;
  error(message: string, data?: Record<string, unknown>): void;
}

/** No-op logger that silently discards all messages. */
export const noopLogger: Logger = {
  debug() {},
  info() {},
  warn() {},
  error() {},
};
