import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { QueryBuildRequest, QueryBuildResponse } from "@/api/generated/initiativeAPI.schemas";
import { buildQueryApiV1GGuildIdQueryBuildPost } from "@/api/generated/query/query";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { QueryOpts } from "@/types/query";

/**
 * Turn what somebody clicked into a statement, and say what it would return.
 *
 * The builder describes; the server writes the SQL. That is what makes a
 * click-built query one the surface will always run — the statement is built in
 * the parse tree rather than assembled as text here, so quoting a name or a
 * value somebody typed is never this file's problem.
 *
 * Keyed on the whole description, because the description *is* the request, and
 * the last good answer is kept while a new one is in flight so the preview does
 * not blink on every click.
 */
export const queryBuildKey = (guildId: number, spec: QueryBuildRequest | null) =>
  ["query-build", guildId, spec] as const;

export const useQueryBuilder = (
  spec: QueryBuildRequest | null,
  options?: QueryOpts<QueryBuildResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<QueryBuildResponse>({
    queryKey: queryBuildKey(guildId, spec),
    queryFn: () => buildQueryApiV1GGuildIdQueryBuildPost(guildId, spec as QueryBuildRequest),
    placeholderData: keepPreviousData,
    // A description either builds or it does not; retrying asks the same
    // question again.
    retry: false,
    ...options,
    enabled: Boolean(spec?.columns.length) && (options?.enabled ?? true),
  });
};
