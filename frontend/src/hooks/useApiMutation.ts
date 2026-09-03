import { useMutation } from "@tanstack/react-query";

import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { MutationOpts } from "@/types/mutation";

/**
 * Shared config for the domain mutation hooks.
 *
 * `mutationFn` must return `Promise<TData>` — the Orval-generated fetchers are
 * genuinely typed (the Axios mutator unwraps `.data` and is typed to match),
 * so a mismatch here means the hook's declared type disagrees with the API
 * schema and should be fixed, not cast away.
 */
interface ApiMutationConfig<TData, TVariables> {
  /** Perform the request. The runtime result is the unwrapped payload. */
  mutationFn: (variables: TVariables) => Promise<TData>;
  /**
   * Invalidations fired on success, before the caller's `onSuccess`.
   * Receives the mutation result and variables; the return value is not
   * awaited (fire-and-forget, matching the hand-written hooks).
   */
  invalidate?: (data: TData, variables: TVariables) => unknown;
  /** `getErrorMessage` fallback key for the error toast. Omit to skip the toast. */
  errorKey?: string;
}

/**
 * Base mutation hook for personal/platform endpoints: composes the caller's
 * `onSuccess`/`onError`/`onSettled` with the hook's invalidation + error toast.
 */
export function useApiMutation<TData, TVariables = void>(
  config: ApiMutationConfig<TData, TVariables>,
  options?: MutationOpts<TData, TVariables>
) {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};

  return useMutation<TData, Error, TVariables>({
    ...rest,
    mutationFn: (variables) => config.mutationFn(variables),
    onSuccess: (...args) => {
      void config.invalidate?.(args[0], args[1]);
      onSuccess?.(...args);
    },
    onError: (...args) => {
      if (config.errorKey) toast.error(getErrorMessage(args[0], config.errorKey));
      onError?.(...args);
    },
    onSettled,
  });
}

interface GuildMutationConfig<TData, TVariables> {
  /** Perform the request against the active guild (from the route path). */
  mutationFn: (guildId: number, variables: TVariables) => Promise<TData>;
  invalidate?: (data: TData, variables: TVariables) => unknown;
  errorKey?: string;
}

/**
 * Guild-scoped variant of {@link useApiMutation}: threads the active guild id
 * (derived from the `/c/{guildId}` route) into `mutationFn`. Domain hooks stay
 * as thin named wrappers so their public signatures are unchanged.
 */
export function useGuildMutation<TData, TVariables = void>(
  config: GuildMutationConfig<TData, TVariables>,
  options?: MutationOpts<TData, TVariables>
) {
  const guildId = useActiveGuildId();
  return useApiMutation<TData, TVariables>(
    {
      ...config,
      mutationFn: (variables) => config.mutationFn(guildId, variables),
    },
    options
  );
}
