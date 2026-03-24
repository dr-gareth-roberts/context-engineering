/**
 * Utility for writing code that works with both sync and async values.
 * The sync path never creates Promises (zero overhead).
 */

export type MaybeAsync<T> = T | Promise<T>;

/**
 * Chain a computation onto a MaybeAsync value.
 * If the value is sync, the function is called immediately (no Promise created).
 * If the value is a Promise, it chains via .then().
 */
export function chain<T, U>(
  value: MaybeAsync<T>,
  fn: (v: T) => MaybeAsync<U>
): MaybeAsync<U> {
  if (value instanceof Promise) return value.then(fn);
  return fn(value);
}

/**
 * Resolve an array of MaybeAsync values.
 * If all values are sync, returns a plain array (no Promise).
 */
export function all<T>(values: MaybeAsync<T>[]): MaybeAsync<T[]> {
  if (values.some(v => v instanceof Promise)) {
    return Promise.all(values);
  }
  return values as T[];
}
