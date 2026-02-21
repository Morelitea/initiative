/**
 * Wraps an Orval-generated API function to fix the return type.
 *
 * Orval generates functions that return `Promise<AxiosResponse<T>>` at the type
 * level, but the custom Axios mutator unwraps responses so the runtime value is
 * actually `Promise<T>`. This helper bridges that gap without scattering
 * `as unknown as Promise<T>` across every call site.
 */
export function castQueryFn<T>(fn: () => unknown): () => Promise<T> {
  return fn as () => Promise<T>;
}
