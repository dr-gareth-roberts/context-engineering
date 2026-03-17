/**
 * Generic lazy-loading helper for optional SDK clients.
 *
 * Handles:
 * - Deferred dynamic import (peer dep not loaded until first use)
 * - Promise deduplication (concurrent calls share one import)
 * - Retry on failure (rejected promise is cleared so next call retries)
 */
export function createLazyClient<T>(
  factory: () => Promise<T>
): () => Promise<T> {
  let client: T | null = null;
  let pending: Promise<T> | null = null;

  return () => {
    if (client) return Promise.resolve(client);
    if (!pending) {
      pending = factory()
        .then(c => {
          client = c;
          return c;
        })
        .catch((err: unknown) => {
          // Clear the cached rejection so the next call can retry
          pending = null;
          throw err;
        });
    }
    return pending;
  };
}
