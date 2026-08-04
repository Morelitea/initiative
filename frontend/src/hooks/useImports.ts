import {
  importFromTicktickApiV1GGuildIdImportsTicktickPost,
  importFromTodoistApiV1GGuildIdImportsTodoistPost,
  importFromVikunjaApiV1GGuildIdImportsVikunjaPost,
  parseTicktickCsvApiV1GGuildIdImportsTicktickParsePost,
  parseTodoistCsvApiV1GGuildIdImportsTodoistParsePost,
  parseVikunjaJsonApiV1GGuildIdImportsVikunjaParsePost,
} from "@/api/generated/imports/imports";
import { invalidateAllProjects, invalidateAllTasks } from "@/api/query-keys";
import { useGuildMutation } from "@/hooks/useApiMutation";
import type { MutationOpts } from "@/types/mutation";

// ── Todoist ──────────────────────────────────────────────────────────────────

// The parse endpoints return untyped JSON; consumers define their own result interfaces.
// We use `unknown` so callers can cast the result to their local types.

export const useParseTodoistCsv = (options?: MutationOpts<unknown, string>) =>
  useGuildMutation<unknown, string>(
    {
      mutationFn: (guildId, content) =>
        parseTodoistCsvApiV1GGuildIdImportsTodoistParsePost(guildId, content),
    },
    options
  );

export const useImportFromTodoist = (
  options?: MutationOpts<
    unknown,
    Parameters<typeof importFromTodoistApiV1GGuildIdImportsTodoistPost>[1]
  >
) =>
  useGuildMutation<unknown, Parameters<typeof importFromTodoistApiV1GGuildIdImportsTodoistPost>[1]>(
    {
      mutationFn: (guildId, data) =>
        importFromTodoistApiV1GGuildIdImportsTodoistPost(guildId, data),
      invalidate: () => invalidateAllTasks(),
    },
    options
  );

// ── Vikunja ──────────────────────────────────────────────────────────────────

export const useParseVikunjaJson = (options?: MutationOpts<unknown, string>) =>
  useGuildMutation<unknown, string>(
    {
      mutationFn: (guildId, content) =>
        parseVikunjaJsonApiV1GGuildIdImportsVikunjaParsePost(guildId, content),
    },
    options
  );

export const useImportFromVikunja = (
  options?: MutationOpts<
    unknown,
    Parameters<typeof importFromVikunjaApiV1GGuildIdImportsVikunjaPost>[1]
  >
) =>
  useGuildMutation<unknown, Parameters<typeof importFromVikunjaApiV1GGuildIdImportsVikunjaPost>[1]>(
    {
      mutationFn: (guildId, data) =>
        importFromVikunjaApiV1GGuildIdImportsVikunjaPost(guildId, data),
      invalidate: () => Promise.all([invalidateAllTasks(), invalidateAllProjects()]),
    },
    options
  );

// ── TickTick ─────────────────────────────────────────────────────────────────

export const useParseTickTickCsv = (options?: MutationOpts<unknown, string>) =>
  useGuildMutation<unknown, string>(
    {
      mutationFn: (guildId, content) =>
        parseTicktickCsvApiV1GGuildIdImportsTicktickParsePost(guildId, content),
    },
    options
  );

export const useImportFromTickTick = (
  options?: MutationOpts<
    unknown,
    Parameters<typeof importFromTicktickApiV1GGuildIdImportsTicktickPost>[1]
  >
) =>
  useGuildMutation<
    unknown,
    Parameters<typeof importFromTicktickApiV1GGuildIdImportsTicktickPost>[1]
  >(
    {
      mutationFn: (guildId, data) =>
        importFromTicktickApiV1GGuildIdImportsTicktickPost(guildId, data),
      invalidate: () => invalidateAllTasks(),
    },
    options
  );
