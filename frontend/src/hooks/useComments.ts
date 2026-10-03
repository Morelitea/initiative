import {
  type InfiniteData,
  infiniteQueryOptions,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createComment,
  deleteComment,
  getListCommentsQueryKey,
  getRecentCommentsQueryKey,
  listComments,
  readComment,
  recentComments,
  updateComment,
} from "@/api/generated/comments/comments";
import type {
  CommentListResponse,
  CommentRead,
  ListCommentsParams,
  RecentActivityEntry,
  RecentCommentsParams,
} from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { getHttpStatus } from "@/lib/errorMessage";
import { queryClient } from "@/lib/queryClient";
import { singularOf } from "@/lib/tools";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Conversations per page — a top-level comment and every reply under it. */
const COMMENT_PAGE_SIZE = 20;

/** Which thread: exactly one `{target}_id`. The page size and the cursor are
 *  the query's own, so they stay out of the key. */
export type CommentThreadParams = Omit<ListCommentsParams, "limit" | "cursor">;

type CommentThreadData = InfiniteData<CommentListResponse>;

/** One thread as an infinite query — shared by the hook and the route loaders
 *  that warm it, so both land in the same cache entry. */
export const commentThreadQueryOptions = (guildId: number, params: CommentThreadParams) =>
  infiniteQueryOptions({
    queryKey: getListCommentsQueryKey(guildId, params),
    queryFn: ({ pageParam, signal }) =>
      listComments(
        guildId,
        { ...params, limit: COMMENT_PAGE_SIZE, cursor: pageParam },
        undefined,
        signal
      ),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: CommentListResponse) => last.next_cursor ?? undefined,
  });

/** Every loaded comment as one list. A conversation put on the first page as
 *  it arrived (one restored from the trash, say) can turn up again on an
 *  older page loaded afterwards; it is listed once. */
const flattenThread = (data: CommentThreadData) => {
  const seen = new Set<number>();
  return data.pages
    .flatMap((page) => page.comments)
    .filter((comment) => {
      if (seen.has(comment.id)) return false;
      seen.add(comment.id);
      return true;
    });
};

/**
 * One comment thread, newest conversations first, a page at a time.
 *
 * `data` is every comment loaded so far as one list; `fetchNextPage` brings
 * the next older page of conversations.
 */
export const useComments = (params: CommentThreadParams, options?: { enabled?: boolean }) => {
  const guildId = useActiveGuildId();
  return useInfiniteQuery({
    ...commentThreadQueryOptions(guildId, params),
    select: flattenThread,
    enabled: options?.enabled,
  });
};

export const useRecentComments = (
  params?: RecentCommentsParams,
  options?: QueryOpts<RecentActivityEntry[]>
) => {
  const guildId = useActiveGuildId();
  return useQuery<RecentActivityEntry[]>({
    queryKey: getRecentCommentsQueryKey(guildId, params),
    queryFn: () => recentComments(guildId, params),
    staleTime: 30 * 1000,
    ...options,
  });
};

// ── Cache helpers ───────────────────────────────────────────────────────────

const mapPages = (
  data: CommentThreadData,
  update: (comments: CommentRead[], index: number) => CommentRead[]
): CommentThreadData => ({
  ...data,
  pages: data.pages.map((page, index) => ({ ...page, comments: update(page.comments, index) })),
});

/**
 * Put one comment where the thread shows it: in place when it is already
 * loaded; a new conversation at the end of the first page, the newest one; a
 * new reply after the rest of its conversation, on the page that holds it. A
 * reply to a conversation not loaded yet arrives with that conversation's page.
 */
const placeComment = (data: CommentThreadData, comment: CommentRead): CommentThreadData => {
  const holds = (id: number) => (page: CommentListResponse) =>
    page.comments.some((c) => c.id === id);
  if (data.pages.some(holds(comment.id))) {
    return mapPages(data, (comments) => comments.map((c) => (c.id === comment.id ? comment : c)));
  }
  const pageIndex =
    comment.parent_comment_id == null ? 0 : data.pages.findIndex(holds(comment.parent_comment_id));
  if (pageIndex === -1 || pageIndex >= data.pages.length) return data;
  return mapPages(data, (comments, index) =>
    index === pageIndex ? [...comments, comment] : comments
  );
};

/** Take a comment out, with every reply under it — they go to the trash with it. */
const dropComment = (data: CommentThreadData, commentId: number): CommentThreadData => {
  const gone = new Set([commentId]);
  // A conversation sits on one page in the order it was written, so a reply
  // is always reached after the comment it answers.
  return mapPages(data, (comments) =>
    comments.filter((c) => {
      if (c.parent_comment_id != null && gone.has(c.parent_comment_id)) gone.add(c.id);
      return !gone.has(c.id);
    })
  );
};

export const useCommentsCache = (params: CommentThreadParams) => {
  const guildId = useActiveGuildId();
  const qc = useQueryClient();
  const { queryKey } = commentThreadQueryOptions(guildId, params);

  /** A comment just posted or edited, written straight into the thread. */
  const putComment = (comment: CommentRead) => {
    qc.setQueryData(queryKey, (prev) => prev && placeComment(prev, comment));
  };

  const removeComment = (commentId: number) => {
    qc.setQueryData(queryKey, (prev) => prev && dropComment(prev, commentId));
  };

  return { putComment, removeComment };
};

/**
 * The thread a comment belongs to: the one target it names. A task comment
 * also reports its task's project, so the task is read first, as the backend
 * reads a comment's columns.
 */
const COMMENT_TARGETS = [
  "task_id",
  "wiki_page_id",
  "document_id",
  "project_id",
  "queue_id",
  "counter_group_id",
  "calendar_id",
  "dashboard_id",
  "post_id",
  "gallery_id",
  "wiki_id",
] as const satisfies readonly (keyof CommentThreadParams & keyof CommentRead)[];

const inThread = (comment: CommentRead, params: CommentThreadParams) => {
  const target = COMMENT_TARGETS.find((key) => comment[key] != null);
  return target !== undefined && params[target] === comment[target];
};

/** The cached threads of `parent`. */
const threadsOf = (guildId: number, parent: { type: string; id: number }) => {
  const param = `${singularOf(parent.type)}_id` as keyof CommentThreadParams;
  return queryClient
    .getQueryCache()
    .findAll({ queryKey: getListCommentsQueryKey(guildId) })
    .filter((query) => {
      const params = query.queryKey[1] as CommentThreadParams | undefined;
      return params?.[param] === parent.id;
    });
};

const readBack = async (
  guildId: number,
  parent: { type: string; id: number },
  commentIds: readonly number[]
) => {
  const threads = threadsOf(guildId, parent);
  const refetch = () =>
    Promise.all(
      threads.map((thread) =>
        queryClient.invalidateQueries({ queryKey: thread.queryKey, exact: true })
      )
    );
  // A thread nobody is showing is only marked stale, and reads again when it
  // is next shown.
  if (!threads.some((thread) => thread.getObserversCount() > 0)) {
    await refetch();
    return;
  }
  if (commentIds.length > COMMENT_PAGE_SIZE) {
    await refetch();
    return;
  }
  let reads: (CommentRead | number)[];
  try {
    // In id order, so a reply written in the same batch as the comment it
    // answers is placed after it.
    reads = await Promise.all(
      [...commentIds]
        .sort((a, b) => a - b)
        .map((id) =>
          readComment(guildId, id).catch((error: unknown) => {
            if (getHttpStatus(error) === 404) return id;
            throw error;
          })
        )
    );
  } catch {
    await refetch();
    return;
  }
  for (const thread of threads) {
    const params = thread.queryKey[1] as CommentThreadParams;
    queryClient.setQueryData<CommentThreadData>(
      thread.queryKey,
      (prev) =>
        prev &&
        reads.reduce(
          (data, read) =>
            typeof read === "number"
              ? dropComment(data, read)
              : inThread(read, params)
                ? placeComment(data, read)
                : data,
          prev
        )
    );
  }
};

/** Read-backs run one batch at a time, so an earlier batch's reply can never
 *  land after a later one's. */
let pendingSync: Promise<void> = Promise.resolve();

/**
 * Bring the comments a realtime frame named under `parent` into the threads
 * this tab has open.
 *
 * Each is read back on its own (`GET /comments/{id}`, the same access check
 * as the thread) and placed in the thread it names, so the open pages are
 * never fetched again for one new comment. One that no longer reads back has
 * been deleted, or the reader can no longer see it, and comes out. More than
 * a page's worth at once, or a read that fails for any other reason, reads the
 * threads again instead.
 */
export const syncComments = (
  guildId: number,
  parent: { type: string; id: number },
  commentIds: readonly number[]
) => {
  pendingSync = pendingSync.then(() => readBack(guildId, parent, commentIds));
  return pendingSync;
};

// ── Mutations ───────────────────────────────────────────────────────────────

export const useCreateComment = (
  options?: MutationOpts<CommentRead, Parameters<typeof createComment>[1]>
) =>
  useGuildMutation<CommentRead, Parameters<typeof createComment>[1]>(
    {
      mutationFn: (guildId, data) => createComment(guildId, data),
      invalidate: () => invalidate(q.recentComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

export const useUpdateComment = (
  options?: MutationOpts<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateComment>[2];
    }
  >
) =>
  useGuildMutation<
    CommentRead,
    {
      commentId: number;
      data: Parameters<typeof updateComment>[2];
    }
  >(
    {
      mutationFn: (guildId, { commentId, data }) => updateComment(guildId, commentId, data),
      invalidate: () => invalidate(q.recentComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );

export const useDeleteComment = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, commentId) => deleteComment(guildId, commentId),
      invalidate: () => invalidate(q.recentComments(), q.relationships()),
      errorKey: "common:error",
    },
    options
  );
