/**
 * Shared hash utility for cache keys and content identity.
 *
 * Uses a 64-bit FNV-1a-inspired hash (two 32-bit halves) to reduce
 * collision probability compared to a single 32-bit hash.
 * With the birthday paradox, collisions become likely at ~2^32 (~4 billion)
 * unique inputs rather than ~2^16 (~65,000) with a 32-bit hash.
 *
 * Not cryptographic — suitable for cache identity and content comparison only.
 */

/**
 * Compute a 64-bit hash of a string, returned as a base-36 string.
 *
 * Uses two independent 32-bit hash rounds (different primes) concatenated
 * to produce a wider hash with lower collision probability.
 *
 * @param str - The string to hash
 * @returns A base-36 encoded hash string
 */
export function hash64(str: string): string {
  // First 32-bit hash (DJB2-like with multiply-shift)
  let h1 = 0;
  for (let i = 0; i < str.length; i++) {
    h1 = ((h1 << 5) - h1 + str.charCodeAt(i)) | 0;
  }

  // Second 32-bit hash (FNV-1a-like with different prime)
  let h2 = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h2 ^= str.charCodeAt(i);
    h2 = Math.imul(h2, 0x01000193);
  }

  return (h1 >>> 0).toString(36) + (h2 >>> 0).toString(36);
}
