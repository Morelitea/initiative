import { useMutation } from "@tanstack/react-query";

import {
  importFromTicktickApiV1GGuildIdImportsTicktickPost,
  importFromTodoistApiV1GGuildIdImportsTodoistPost,
  importFromVikunjaApiV1GGuildIdImportsVikunjaPost,
  parseTicktickCsvApiV1GGuildIdImportsTicktickParsePost,
  parseTodoistCsvApiV1GGuildIdImportsTodoistParsePost,
  parseVikunjaJsonApiV1GGuildIdImportsVikunjaParsePost,
} from "@/api/generated/imports/imports";
import { invalidateAllProjects, invalidateAllTasks } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { MutationOpts } from "@/types/mutation";

// ── Todoist ──────────────────────────────────────────────────────────────────

// The parse endpoints return untyped JSON; consumers define their own result interfaces.
// We use `unknown` so callers can cast the result to their local types.

export const useParseTodoistCsv = (options?: MutationOpts<unknown, string>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (content: string) => {
      return parseTodoistCsvApiV1GGuildIdImportsTodoistParsePost(
        guildId,
        content
      ) as unknown as Promise<unknown>;
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useImportFromTodoist = (
  options?: MutationOpts<
    unknown,
    Parameters<typeof importFromTodoistApiV1GGuildIdImportsTodoistPost>[1]
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (
      data: Parameters<typeof importFromTodoistApiV1GGuildIdImportsTodoistPost>[1]
    ) => {
      return importFromTodoistApiV1GGuildIdImportsTodoistPost(
        guildId,
        data
      ) as unknown as Promise<unknown>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

// ── Vikunja ──────────────────────────────────────────────────────────────────

export const useParseVikunjaJson = (options?: MutationOpts<unknown, string>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (content: string) => {
      return parseVikunjaJsonApiV1GGuildIdImportsVikunjaParsePost(
        guildId,
        content
      ) as unknown as Promise<unknown>;
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useImportFromVikunja = (
  options?: MutationOpts<
    unknown,
    Parameters<typeof importFromVikunjaApiV1GGuildIdImportsVikunjaPost>[1]
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (
      data: Parameters<typeof importFromVikunjaApiV1GGuildIdImportsVikunjaPost>[1]
    ) => {
      return importFromVikunjaApiV1GGuildIdImportsVikunjaPost(
        guildId,
        data
      ) as unknown as Promise<unknown>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      void invalidateAllProjects();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

// ── TickTick ─────────────────────────────────────────────────────────────────

export const useParseTickTickCsv = (options?: MutationOpts<unknown, string>) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (content: string) => {
      return parseTicktickCsvApiV1GGuildIdImportsTicktickParsePost(
        guildId,
        content
      ) as unknown as Promise<unknown>;
    },
    onSuccess: (...args) => {
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};

export const useImportFromTickTick = (
  options?: MutationOpts<
    unknown,
    Parameters<typeof importFromTicktickApiV1GGuildIdImportsTicktickPost>[1]
  >
) => {
  const guildId = useActiveGuildId();
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (
      data: Parameters<typeof importFromTicktickApiV1GGuildIdImportsTicktickPost>[1]
    ) => {
      return importFromTicktickApiV1GGuildIdImportsTicktickPost(
        guildId,
        data
      ) as unknown as Promise<unknown>;
    },
    onSuccess: (...args) => {
      void invalidateAllTasks();
      onSuccess?.(...args);
    },
    onError: (...args) => {
      onError?.(...args);
    },
    onSettled,
  });
};
