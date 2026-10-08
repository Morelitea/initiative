import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { QueryShapeResponse } from "@/api/generated/initiativeAPI.schemas";
import { describeQuery } from "@/api/generated/query/query";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { QueryOpts } from "@/types/query";

/**
 * What a statement would return, without running it.
 *
 * The check behind a hand-written query: the server reads it the way it will
 * read it for real and answers with the columns or with the word that has to
 * change. It plans and returns no rows, so asking on every pause costs a parse
 * and a plan however much data the statement would have touched.
 *
 * The last good answer is kept while a new one is in flight, so the columns a
 * widget is mapped against do not blink away mid-keystroke.
 */
export const queryShapeKey = (communityId: number, sql: string, initiativeId?: number) =>
  ["query-describe", communityId, sql, initiativeId ?? null] as const;

export const useQueryShape = (
  sql: string | null,
  initiativeId: number | undefined,
  options?: QueryOpts<QueryShapeResponse>
) => {
  const communityId = useActiveCommunityId();
  return useQuery<QueryShapeResponse>({
    queryKey: queryShapeKey(communityId, sql ?? "", initiativeId),
    queryFn: () =>
      describeQuery(communityId, {
        sql: sql ?? "",
        initiative_id: initiativeId,
      }),
    placeholderData: keepPreviousData,
    // A statement either resolves against the registry or it does not, and a
    // refused one is refused the same way every time.
    retry: false,
    ...options,
    enabled: Boolean(sql?.trim()) && (options?.enabled ?? true),
  });
};
