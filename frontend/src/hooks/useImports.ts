import { useMutation } from "@tanstack/react-query";

import {
  parseTodoistCsvApiV1ImportsTodoistParsePost,
  importFromTodoistApiV1ImportsTodoistPost,
  parseVikunjaJsonApiV1ImportsVikunjaParsePost,
  importFromVikunjaApiV1ImportsVikunjaPost,
  parseTicktickCsvApiV1ImportsTicktickParsePost,
  importFromTicktickApiV1ImportsTicktickPost,
} from "@/api/generated/imports/imports";
import { invalidateAllTasks, invalidateAllProjects } from "@/api/query-keys";
import type { MutationOpts } from "@/types/mutation";

// ── Todoist ──────────────────────────────────────────────────────────────────

// The parse endpoints return untyped JSON; consumers define their own result interfaces.
// We use `unknown` so callers can cast the result to their local types.

export const useParseTodoistCsv = (options?: MutationOpts<unknown, string>) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (content: string) => {
      return parseTodoistCsvApiV1ImportsTodoistParsePost(content) as unknown as Promise<unknown>;
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
  options?: MutationOpts<unknown, Parameters<typeof importFromTodoistApiV1ImportsTodoistPost>[0]>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof importFromTodoistApiV1ImportsTodoistPost>[0]) => {
      return importFromTodoistApiV1ImportsTodoistPost(data) as unknown as Promise<unknown>;
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (content: string) => {
      return parseVikunjaJsonApiV1ImportsVikunjaParsePost(content) as unknown as Promise<unknown>;
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
  options?: MutationOpts<unknown, Parameters<typeof importFromVikunjaApiV1ImportsVikunjaPost>[0]>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof importFromVikunjaApiV1ImportsVikunjaPost>[0]) => {
      return importFromVikunjaApiV1ImportsVikunjaPost(data) as unknown as Promise<unknown>;
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
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (content: string) => {
      return parseTicktickCsvApiV1ImportsTicktickParsePost(content) as unknown as Promise<unknown>;
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
  options?: MutationOpts<unknown, Parameters<typeof importFromTicktickApiV1ImportsTicktickPost>[0]>
) => {
  const { onSuccess, onError, onSettled, ...rest } = options ?? {};
  return useMutation({
    ...rest,
    mutationFn: async (data: Parameters<typeof importFromTicktickApiV1ImportsTicktickPost>[0]) => {
      return importFromTicktickApiV1ImportsTicktickPost(data) as unknown as Promise<unknown>;
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
