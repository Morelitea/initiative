import type { UseQueryOptions } from "@tanstack/react-query";

/**
 * Shared query options type for domain hooks.
 *
 * Omits `queryKey` and `queryFn` since the hook owns them.
 * Callers can pass any other query option (enabled, staleTime, gcTime, etc.)
 * and the hook will merge them with its defaults.
 */
export type QueryOpts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn">;
