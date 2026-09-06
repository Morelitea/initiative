import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import type {
  GetPostTimelineApiV1GGuildIdPostsTimelineGetParams,
  InitiativeGroupedCountsResponse,
  ListPostsApiV1GGuildIdPostsGetParams,
  PollRead,
  PollVoters,
  PollVoteWrite,
  PollWrite,
  PostCreate,
  PostListResponse,
  PostPinUpdate,
  PostRead,
  PostReaders,
  PostReadMarks,
  PostReadReceipt,
  PostUpdate,
  ResourceGrantSchema,
  TimelineResponse,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPostApiV1GGuildIdPostsPost,
  deletePostApiV1GGuildIdPostsPostIdDelete,
  deletePostPollApiV1GGuildIdPostsPostIdPollDelete,
  getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey,
  getGetPostTimelineApiV1GGuildIdPostsTimelineGetQueryKey,
  getListPostPollVotersApiV1GGuildIdPostsPostIdPollVotersGetQueryKey,
  getListPostReadersApiV1GGuildIdPostsPostIdReadsGetQueryKey,
  getListPostsApiV1GGuildIdPostsGetQueryKey,
  getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet,
  getPostTimelineApiV1GGuildIdPostsTimelineGet,
  getReadPostApiV1GGuildIdPostsPostIdGetQueryKey,
  listPostPollVotersApiV1GGuildIdPostsPostIdPollVotersGet,
  listPostReadersApiV1GGuildIdPostsPostIdReadsGet,
  listPostsApiV1GGuildIdPostsGet,
  markPostsReadApiV1GGuildIdPostsReadPost,
  markPostUnreadApiV1GGuildIdPostsPostIdReadDelete,
  readPostApiV1GGuildIdPostsPostIdGet,
  retractPostPollVoteApiV1GGuildIdPostsPostIdPollVoteDelete,
  setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut,
  setPostPinApiV1GGuildIdPostsPostIdPinPut,
  setPostPollApiV1GGuildIdPostsPostIdPollPut,
  updatePostApiV1GGuildIdPostsPostIdPatch,
  voteOnPostPollApiV1GGuildIdPostsPostIdPollVotePut,
} from "@/api/generated/posts/posts";
import { invalidateAllPosts, invalidatePost, patchCachedPost } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useGuildMutation } from "@/hooks/useApiMutation";
import { queryClient } from "@/lib/queryClient";
import type { MutationOpts } from "@/types/mutation";
import type { QueryOpts } from "@/types/query";

// ── Queries ─────────────────────────────────────────────────────────────────

/** Visible-post counts per initiative, for the sidebar badges. */
export const usePostCountsByInitiative = (options?: QueryOpts<InitiativeGroupedCountsResponse>) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeGroupedCountsResponse>({
    queryKey: getGetPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGetQueryKey(guildId),
    queryFn: () => getPostCountsByInitiativeApiV1GGuildIdPostsCountsByInitiativeGet(guildId),
    ...options,
  });
};

/**
 * One page of a board.
 *
 * Unlike every other tool list this carries whole posts — a board renders its
 * notices — so the server pages it in twenties. `keepPreviousData` keeps the
 * current page on screen while the next one loads, rather than blanking the
 * board between pages.
 */
export const usePostsList = (
  params?: ListPostsApiV1GGuildIdPostsGetParams,
  options?: QueryOpts<PostListResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<PostListResponse>({
    queryKey: getListPostsApiV1GGuildIdPostsGetQueryKey(guildId, params),
    queryFn: () => listPostsApiV1GGuildIdPostsGet(guildId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/**
 * The board, page by page, as somebody scrolls it.
 *
 * A board is read downwards, not paged through, so this is an infinite query
 * rather than a page cursor in the URL. Pages are small — five — because each
 * row is a body the client mounts an editor for, and what a page bounds is how
 * much is fetched ahead of the reader, not how much they have to look at.
 */
export const usePostsFeed = (params?: ListPostsApiV1GGuildIdPostsGetParams) => {
  const guildId = useActiveGuildId();
  return useInfiniteQuery({
    queryKey: getListPostsApiV1GGuildIdPostsGetQueryKey(guildId, params),
    queryFn: ({ pageParam }) =>
      listPostsApiV1GGuildIdPostsGet(guildId, { ...params, page: pageParam as number }),
    initialPageParam: 1,
    getNextPageParam: (last: PostListResponse) => (last.has_next ? last.page + 1 : undefined),
    placeholderData: keepPreviousData,
  });
};

/**
 * Who has read a notice, and who it is still waiting on.
 *
 * Fetched when somebody asks — the count is on the card, and the roster behind
 * it is a click. A board of five cards should not fetch five rosters nobody
 * opened.
 */
export const usePostReaders = (postId: number, options?: QueryOpts<PostReaders>) => {
  const guildId = useActiveGuildId();
  return useQuery<PostReaders>({
    queryKey: getListPostReadersApiV1GGuildIdPostsPostIdReadsGetQueryKey(guildId, postId),
    queryFn: () => listPostReadersApiV1GGuildIdPostsPostIdReadsGet(guildId, postId),
    ...options,
  });
};

/**
 * The months this board has notices in — what the timeline rail is drawn from.
 *
 * Takes the same filters the feed does, because the rail is a picture of the
 * feed as it currently stands: with the unread filter on, a month that is
 * fully read is not a stop worth offering. The reader's own zone goes with it,
 * since a month is a boundary in somebody's day.
 */
export const usePostsTimeline = (
  params?: GetPostTimelineApiV1GGuildIdPostsTimelineGetParams,
  options?: QueryOpts<TimelineResponse>
) => {
  const guildId = useActiveGuildId();
  return useQuery<TimelineResponse>({
    queryKey: getGetPostTimelineApiV1GGuildIdPostsTimelineGetQueryKey(guildId, params),
    queryFn: () => getPostTimelineApiV1GGuildIdPostsTimelineGet(guildId, params),
    ...options,
  });
};

export const usePost = (postId: number | null, options?: QueryOpts<PostRead>) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<PostRead>({
    queryKey: getReadPostApiV1GGuildIdPostsPostIdGetQueryKey(guildId, postId!),
    queryFn: () => readPostApiV1GGuildIdPostsPostIdGet(guildId, postId!),
    enabled: postId !== null && Number.isFinite(postId) && userEnabled,
    ...rest,
  });
};

// ── Mutations ───────────────────────────────────────────────────────────────

const invalidatePostAndList = (postId: number) =>
  Promise.all([invalidatePost(postId), invalidateAllPosts()]);

export const useCreatePost = (options?: MutationOpts<PostRead, PostCreate>) =>
  useGuildMutation<PostRead, PostCreate>(
    {
      mutationFn: (guildId, data) => createPostApiV1GGuildIdPostsPost(guildId, data),
      invalidate: () => invalidateAllPosts(),
      errorKey: "posts:error",
    },
    options
  );

export const useUpdatePost = (postId: number, options?: MutationOpts<PostRead, PostUpdate>) => {
  const guildId = useActiveGuildId();
  return useGuildMutation<PostRead, PostUpdate>(
    {
      mutationFn: (guildId, data) => updatePostApiV1GGuildIdPostsPostIdPatch(guildId, postId, data),
      invalidate: (updated) => {
        // The PATCH answers with the row a refetch would fetch, so seed it
        // rather than leaving the cache on the pre-save copy until the refetch
        // lands — otherwise the editor shows the old body for a beat.
        queryClient.setQueryData(
          getReadPostApiV1GGuildIdPostsPostIdGetQueryKey(guildId, postId),
          updated
        );
        return invalidatePostAndList(postId);
      },
      errorKey: "posts:error",
    },
    options
  );
};

/**
 * Pin a notice to the top of its board, or take it down.
 *
 * Invalidates the whole list rather than patching the cached row: pinning
 * changes the board's *order*, not just this post, so every page of it is
 * stale.
 */
export const useSetPostPin = (postId: number, options?: MutationOpts<PostRead, PostPinUpdate>) =>
  useGuildMutation<PostRead, PostPinUpdate>(
    {
      mutationFn: (guildId, data) =>
        setPostPinApiV1GGuildIdPostsPostIdPinPut(guildId, postId, data),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

/**
 * Write one post's read state into every cached copy of it.
 *
 * The count moves with it: marking read adds this reader to it, marking unread
 * takes them back off, so "Read by 12" does not sit there contradicting the
 * button beside it.
 */
const setCachedReadState = (postId: number, isRead: boolean) =>
  patchCachedPost(postId, (post) => {
    if (post.is_read === isRead) return post;
    const count = typeof post.read_count === "number" ? post.read_count : 0;
    return { ...post, is_read: isRead, read_count: Math.max(0, count + (isRead ? 1 : -1)) };
  });

/**
 * Tell the server which notices have been on screen.
 *
 * Deliberately does NOT invalidate. Read state changes continuously as
 * somebody scrolls, and refetching for it would move rows under the cursor —
 * and with the unread filter on, delete the one being read. The cached copies
 * are patched instead.
 *
 * Patched on the way OUT rather than on the way back, because nothing here
 * refetches: without an optimistic write the card would keep saying unread
 * until something else happened to refresh it. Put back if the request fails,
 * so a dropped connection does not quietly mark a board read.
 */
export const useMarkPostsRead = (options?: MutationOpts<PostReadReceipt, PostReadMarks>) =>
  useGuildMutation<PostReadReceipt, PostReadMarks>(
    {
      mutationFn: (guildId, data) => markPostsReadApiV1GGuildIdPostsReadPost(guildId, data),
      errorKey: "posts:error",
    },
    {
      ...options,
      // Rest args rather than a named signature, so this composes with
      // whatever arity react-query hands the caller's own callbacks.
      onMutate: (...args) => {
        for (const id of args[0].post_ids) setCachedReadState(id, true);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        for (const id of args[1].post_ids) setCachedReadState(id, false);
        options?.onError?.(...args);
      },
    }
  );

/**
 * Put one notice back to unread.
 *
 * Optimistic for the same reason: this is a button somebody pressed, and
 * nothing invalidates behind it, so the card has to answer immediately or look
 * broken. Restored on failure.
 */
export const useMarkPostUnread = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, postId) =>
        markPostUnreadApiV1GGuildIdPostsPostIdReadDelete(guildId, postId),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedReadState(args[0], false);
        return options?.onMutate?.(...args);
      },
      onError: (...args) => {
        setCachedReadState(args[1], true);
        options?.onError?.(...args);
      },
    }
  );

// ── Polls ───────────────────────────────────────────────────────────────────

/**
 * Who chose what on a notice's poll.
 *
 * Fetched when somebody asks, like the read roster: the tallies are already on
 * the card, and the names behind them are a click.
 */
export const usePostPollVoters = (postId: number, options?: QueryOpts<PollVoters>) => {
  const guildId = useActiveGuildId();
  return useQuery<PollVoters>({
    queryKey: getListPostPollVotersApiV1GGuildIdPostsPostIdPollVotersGetQueryKey(guildId, postId),
    queryFn: () => listPostPollVotersApiV1GGuildIdPostsPostIdPollVotersGet(guildId, postId),
    ...options,
  });
};

/**
 * Write the whole post back into every cache that holds it.
 *
 * Every poll route answers with the notice a read would return, so seeding is
 * enough and nothing has to refetch. Deliberately NOT an invalidation: a vote
 * does not change the board's order, and refetching the feed for one would
 * move rows under the cursor mid-scroll.
 */
const seedCachedPost = (post: PostRead) =>
  patchCachedPost(post.id, () => post as unknown as Record<string, unknown>);

/**
 * This ballot, applied to the poll on screen.
 *
 * Derivable in full: the ids that changed move their own tally by one, and the
 * voter count moves only when somebody goes from having answered to not, or
 * back. The one case it cannot answer is a poll whose numbers are still hidden
 * — there is nothing on the client to add one to — so it records the ballot
 * and leaves the reveal to the response.
 */
const applyBallot = (poll: PollRead, optionIds: number[]): PollRead => {
  const after = new Set(optionIds);
  const hadVoted = poll.options.some((option) => option.voted_by_me);
  const hasVoted = after.size > 0;
  const options = poll.options.map((option) => {
    const now = after.has(option.id);
    if (now === option.voted_by_me) return option;
    const count = option.vote_count;
    return {
      ...option,
      voted_by_me: now,
      vote_count: typeof count === "number" ? Math.max(0, count + (now ? 1 : -1)) : count,
    };
  });
  if (!poll.results_visible) {
    return { ...poll, options, has_voted: hasVoted };
  }
  const total = poll.total_voters ?? 0;
  const delta = hasVoted === hadVoted ? 0 : hasVoted ? 1 : -1;
  return { ...poll, options, has_voted: hasVoted, total_voters: total + delta };
};

const setCachedBallot = (postId: number, optionIds: number[]) =>
  patchCachedPost(postId, (post) => {
    const poll = post.poll as PollRead | null | undefined;
    if (!poll) return post;
    return { ...post, poll: applyBallot(poll, optionIds) };
  });

/**
 * Give a notice its question, or rewrite the one it has.
 *
 * Invalidates rather than seeding: writing a poll is an edit of the notice, so
 * the surfaces that count or excerpt it are stale too.
 */
export const useSetPostPoll = (postId: number, options?: MutationOpts<PostRead, PollWrite>) =>
  useGuildMutation<PostRead, PollWrite>(
    {
      mutationFn: (guildId, data) =>
        setPostPollApiV1GGuildIdPostsPostIdPollPut(guildId, postId, data),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

export const useDeletePostPoll = (postId: number, options?: MutationOpts<PostRead, void>) =>
  useGuildMutation<PostRead, void>(
    {
      mutationFn: (guildId) => deletePostPollApiV1GGuildIdPostsPostIdPollDelete(guildId, postId),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );

/**
 * Answer a notice's question.
 *
 * Optimistic for the reason marking read is: nothing behind this refetches the
 * board, so the card has to answer the click immediately or look broken. The
 * response then replaces the guess with the server's own count, which is what
 * settles a tally two people moved at once.
 */
export const useVoteOnPostPoll = (
  postId: number,
  options?: MutationOpts<PostRead, PollVoteWrite>
) =>
  useGuildMutation<PostRead, PollVoteWrite>(
    {
      mutationFn: (guildId, data) =>
        voteOnPostPollApiV1GGuildIdPostsPostIdPollVotePut(guildId, postId, data),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedBallot(postId, args[0].option_ids ?? []);
        return options?.onMutate?.(...args);
      },
      onSuccess: (...args) => {
        seedCachedPost(args[0]);
        options?.onSuccess?.(...args);
      },
      // Put the board back the way it was. The cached copy is the only record
      // of the previous ballot, so it is re-read rather than remembered.
      onError: (...args) => {
        invalidatePost(postId);
        options?.onError?.(...args);
      },
    }
  );

export const useRetractPostPollVote = (postId: number, options?: MutationOpts<PostRead, void>) =>
  useGuildMutation<PostRead, void>(
    {
      mutationFn: (guildId) =>
        retractPostPollVoteApiV1GGuildIdPostsPostIdPollVoteDelete(guildId, postId),
      errorKey: "posts:error",
    },
    {
      ...options,
      onMutate: (...args) => {
        setCachedBallot(postId, []);
        return options?.onMutate?.(...args);
      },
      onSuccess: (...args) => {
        seedCachedPost(args[0]);
        options?.onSuccess?.(...args);
      },
      onError: (...args) => {
        invalidatePost(postId);
        options?.onError?.(...args);
      },
    }
  );

export const useDeletePost = (options?: MutationOpts<void, number>) =>
  useGuildMutation<void, number>(
    {
      mutationFn: (guildId, postId) => deletePostApiV1GGuildIdPostsPostIdDelete(guildId, postId),
      invalidate: () => invalidateAllPosts(),
      errorKey: "posts:error",
    },
    options
  );

// ── Grants Mutation (unified resource sharing) ──────────────────────────────

export const useSetPostGrants = (
  postId: number,
  options?: MutationOpts<PostRead, ResourceGrantSchema[]>
) =>
  useGuildMutation<PostRead, ResourceGrantSchema[]>(
    {
      mutationFn: (guildId, grants) =>
        setPostGrantsApiV1GGuildIdPostsPostIdGrantsPut(guildId, postId, grants),
      invalidate: () => invalidatePostAndList(postId),
      errorKey: "posts:error",
    },
    options
  );
