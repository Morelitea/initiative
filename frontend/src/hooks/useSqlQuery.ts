import { useQuery } from "@tanstack/react-query";

import type { QueryResponse } from "@/api/generated/initiativeAPI.schemas";
import { runQueryApiV1GGuildIdQueryPost } from "@/api/generated/query/query";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { QueryOpts } from "@/types/query";

/**
 * Run one statement and cache what it returned.
 *
 * A read that happens to be spelled as a POST — a statement is too long for a
 * query string and would be logged everywhere one goes. So the caching this
 * needs is stated here rather than taken from the generated mutation hook,
 * which has none: two tiles running the same statement share one request, and a
 * canvas of them re-runs on the same terms as every other list on the page.
 *
 * The key carries the statement itself, because the statement *is* the request
 * — and the initiative beside it, because the same statement asked about two
 * initiatives is two different answers.
 */
export const sqlQueryKey = (guildId: number, sql: string, initiativeId?: number) =>
  ["query", guildId, sql, initiativeId ?? null] as const;

/**
 * `initiativeId` narrows the answer to one initiative.
 *
 * A statement names datasets, not a scope, so a surface that belongs to an
 * initiative has to say which one or it gets every initiative its reader is in.
 * The narrowing is applied by the policies on the tables the statement reads,
 * so it removes rows and never adds any.
 */
export const useSqlQuery = (
  sql: string | null,
  initiativeId: number | undefined,
  options?: QueryOpts<QueryResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<QueryResponse>({
    queryKey: sqlQueryKey(guildId, sql ?? "", initiativeId),
    queryFn: () =>
      runQueryApiV1GGuildIdQueryPost(guildId, { sql: sql ?? "", initiative_id: initiativeId }),
    // Not retried: a statement either resolves against the registry or it does
    // not, and a refused one is refused the same way every time.
    retry: false,
    ...options,
    enabled: Boolean(sql) && (options?.enabled ?? true),
  });
};
