import type { UseMutationOptions } from "@tanstack/react-query";

/**
 * Shared mutation options type for domain hooks.
 *
 * Omits `mutationFn` since the hook owns it.
 * Callers can pass any other mutation option (onSuccess, onError, onSettled,
 * retry, gcTime, etc.) and the hook will merge callbacks with its defaults.
 */
export type MutationOpts<TData, TVariables, TError = Error, TContext = unknown> = Omit<
  UseMutationOptions<TData, TError, TVariables, TContext>,
  "mutationFn"
>;
