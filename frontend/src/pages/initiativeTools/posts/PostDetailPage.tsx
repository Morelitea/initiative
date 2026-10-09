import { useBlocker, useNavigate, useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { CalendarClock, Loader2, Vote } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ReactionTarget, SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { PinnedBanner } from "@/components/initiativeTools/posts/PinnedBanner";
import {
  emptyPollDraft,
  isPollDraftValid,
  type PollDraft,
  PollEditor,
  pollDraftFromRead,
  pollDraftToWrite,
} from "@/components/initiativeTools/posts/PollEditor";
import { PostByline } from "@/components/initiativeTools/posts/PostByline";
import { PostPinButton } from "@/components/initiativeTools/posts/PostPinButton";
import { PostPoll } from "@/components/initiativeTools/posts/PostPoll";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { DetailHeaderSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { TagBadge } from "@/components/tags/TagBadge";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useDeletePostPoll, usePost, useSetPostPoll, useUpdatePost } from "@/hooks/usePosts";
import { useRecordRecentView } from "@/hooks/useRecents";
import { useCommunityPath } from "@/lib/communityUrl";
import { normalizeEditorState } from "@/lib/editorState";
import { formatDateTime, fromLocalDateTimeInput, toLocalDateTimeInput } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { MAX_POST_TEXT_CHARS } from "@/lib/posts";
import { referenceRef } from "@/lib/smartChips";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

const Editor = lazy(() =>
  import("@/components/ui/editor/editor").then((m) => ({ default: m.Editor }))
);

/**
 * One notice, on its own page — where its comments and reactions live.
 *
 * The body is the same editor the board renders, switched to editable for
 * anyone with write access on the post. Pinning sits beside it but answers to
 * a different rule: initiative management, not write access, so an author can
 * edit their own notice without being able to lift it above everyone else's.
 */
export function PostDetailPage() {
  const { t } = useTranslation(["posts", "common"]);
  const { communityId, postId } = useParams({ strict: false }) as {
    communityId: string;
    postId: string;
  };
  const parsedId = Number(postId);
  const gp = useCommunityPath();

  const postQuery = usePost(Number.isFinite(parsedId) ? parsedId : null);
  const post = postQuery.data;
  const initiativeId = useCanonicalInitiativeId(post?.initiative_id);

  const recordViewMutation = useRecordRecentView(Tool.post, Number(communityId));
  const viewedPostId = post?.id;
  useReadOnOpen(Tool.post, viewedPostId);
  useEffect(() => {
    if (!viewedPostId) return;
    recordViewMutation.mutate(viewedPostId);
  }, [viewedPostId, recordViewMutation.mutate]);

  const canEdit = Boolean(post?.can.edit);

  const initiativeQuery = useInitiative(post?.initiative_id ?? null);
  const canPin = Boolean(initiativeQuery.data?.can.manage);
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);
  const navigate = useNavigate();

  const update = useUpdatePost(parsedId, {
    onSuccess: () => {
      // Saved is no longer dirty — otherwise the guard goes on asking about an
      // edit that is already on the server.
      setDraft(null);
      toast.success(t("detailsUpdated"));
    },
  });
  // Scheduling gets its OWN mutation, because the one above declares the body
  // saved. Sharing it would let "post now" clear a draft it never sent: the
  // Save button disappears, both navigation guards stand down, and the
  // half-written notice still sitting in the editor leaves with the page.
  const reschedule = useUpdatePost(parsedId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });
  // Renaming gets its own too: the body's mutation clears the unsaved draft.
  const rename = useUpdatePost(parsedId, {
    onSuccess: () => toast.success(t("detailsUpdated")),
  });

  // The editor is uncontrolled once mounted, so the draft lives here and is
  // saved explicitly — a notice is not a collaborative document, and nobody
  // wants a half-written correction broadcast as they type it.
  const [draft, setDraft] = useState<SerializedEditorState | null>(null);

  // The poll is edited in place rather than on the settings page: it is part
  // of what the notice says, and what it says is written here. Null means the
  // editor is closed, not that the notice has no question.
  const [pollDraft, setPollDraft] = useState<PollDraft | null>(null);
  const savePoll = useSetPostPoll(parsedId, {
    onSuccess: () => {
      setPollDraft(null);
      toast.success(t("poll.saved"));
    },
  });
  const removePoll = useDeletePostPoll(parsedId, {
    onSuccess: () => {
      setPollDraft(null);
      toast.success(t("poll.removed"));
    },
  });
  // Answered polls keep their choices and the two switches that can only
  // tighten; the server refuses to change them, and the editor stops offering
  // it rather than letting somebody type an edit that will be rejected.
  //
  // `is_locked`, not a count: on a poll whose results are withheld the count is
  // `null`, so deriving the lock from it would unlock exactly the polls the
  // server is about to refuse.
  const pollAnswered = post?.poll?.is_locked ?? false;

  // An open poll editor is unsaved work too — it is saved by its own button,
  // like the body above it, so leaving the page would take it with them.
  const isDirty = canEdit && (draft !== null || pollDraft !== null);

  // A body full of links, mentions and smart chips is a body full of things
  // that navigate — and an explicit Save means a click on one would otherwise
  // take the unsaved edit with it. Ask first.
  // The same question for a reload or a closed tab. `enableBeforeUnload` is
  // what asks it — and what stops it being asked when there is nothing to
  // lose, since the router defaults it to true and never consults
  // `shouldBlockFn` for an unload.
  const blocker = useBlocker({
    shouldBlockFn: () => isDirty,
    enableBeforeUnload: () => isDirty,
    withResolver: true,
  });

  if (!Number.isFinite(parsedId) || postQuery.isError) {
    return (
      <ToolAccessStatus
        error={postQuery.error}
        keys="posts:"
        backTo={gp(toolListRoute(Tool.post, initiativeId))}
        backLabel={t("backToPosts")}
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      {post ? (
        <ToolPageHeader
          tool={Tool.post}
          initiativeId={post.initiative_id}
          settingsTo={canEdit ? toolSettingsRoute(Tool.post, initiativeId, post.id) : undefined}
          chest={
            <ToolChest tool={Tool.post} entity={post}>
              {canPin ? (
                <ToolChestSegment>
                  <PostPinButton post={post} labelled />
                </ToolChestSegment>
              ) : null}
            </ToolChest>
          }
          title={post.name}
          onRename={canEdit ? (name) => rename.mutateAsync({ name }) : undefined}
          titleExtras={
            <div className="flex items-center gap-1">
              <ReportButton targetType="post" targetId={post.id} authorId={post.created_by} />
              {/* Taken down or held, the notice is gone, so the reader goes
                  back to the board. */}
              <ModerationMenu
                targetType="post"
                targetId={post.id}
                canModerate={canModerate}
                commentsLocked={post.comments_locked_at != null}
                reactable
                communityId={post.community_id}
                onGone={() => void navigate({ to: gp(toolListRoute(Tool.post, initiativeId)) })}
              />
            </div>
          }
        >
          <PostByline post={post} inline />
          <PinnedBanner post={post} canPin={canPin} />
        </ToolPageHeader>
      ) : (
        <DetailHeaderSkeleton actions={0} description={false} />
      )}

      <>
        {/* Reaching this page at all means being able to see the notice, and a
          draft answers 404 to everyone who cannot edit it — so this strip is
          only ever in front of someone who can act on it. It says the state
          and offers the two things there are to do: move the time, or put it
          up now. */}
        {post && !post.is_published && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-dashed p-3">
            {canEdit ? (
              <>
                {/* The picker holds the date, so the label only has to name it.
                  Saying "Scheduled for Sep 9, 4:37 PM" beside a box already
                  reading "Sep 9, 4:37 PM" is the same fact twice, and the one
                  that can be changed is the box. */}
                <Label
                  htmlFor="post-schedule"
                  className="inline-flex items-center gap-1.5 text-muted-foreground text-sm"
                >
                  <CalendarClock className="h-4 w-4" aria-hidden />
                  {t("schedule.publishesAt")}
                </Label>
                <DateTimePicker
                  id="post-schedule"
                  includeTime
                  value={toLocalDateTimeInput(post.scheduled_for)}
                  placeholder={t("schedule.placeholder")}
                  // Only a real instant moves the schedule. Clearing the field
                  // does nothing: publishing cannot be undone, and emptying a
                  // date box to retype it must not announce the notice to
                  // everybody. "Post now" is the way to publish, and it says so.
                  onChange={(value) => {
                    const when = fromLocalDateTimeInput(value);
                    if (when) reschedule.mutate({ scheduled_for: when });
                  }}
                />
                <Button
                  size="sm"
                  className="ml-auto"
                  disabled={reschedule.isPending}
                  onClick={() => reschedule.mutate({ scheduled_for: null })}
                >
                  {t("schedule.publishNow")}
                </Button>
              </>
            ) : (
              // Nothing to change, so the date is the sentence.
              <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
                <CalendarClock className="h-4 w-4" aria-hidden />
                {post.scheduled_for
                  ? t("schedule.scheduledFor", { date: formatDateTime(post.scheduled_for) })
                  : t("schedule.notPublished")}
              </p>
            )}
          </div>
        )}

        {post ? (
          /* What the notice SAYS on the left, what is asked and linked on the
           right — the shape a task already uses. Sized by the column rather
           than by a breakpoint, so a narrow window stacks them instead of
           squeezing both. */
          <div className="grid gap-6 [grid-template-columns:repeat(auto-fit,minmax(min(25rem,100%),1fr))]">
            <div className="min-w-0 space-y-3">
              <Suspense fallback={<Skeleton className="h-40 w-full" />}>
                <Editor
                  key={post.id}
                  editorSerializedState={normalizeEditorState(post.body)}
                  onSerializedChange={setDraft}
                  readOnly={!canEdit}
                  showToolbar={canEdit}
                  initiativeId={post.initiative_id}
                  subject={referenceRef(SearchEntityType.post, post.id)}
                  supportsEntityMentions
                  variant="post"
                  maxLength={MAX_POST_TEXT_CHARS}
                  // A notice sits on a card wherever it is read — on the board,
                  // and here. Reading it, the padding comes from this box, because
                  // the editor's own is the little it needs between cards in a
                  // feed; writing it, the editor already reserves room for the
                  // toolbar and the caret at the end.
                  className={cn("rounded-lg border bg-card", !canEdit && "py-2")}
                />
              </Suspense>
              {canEdit && draft !== null && (
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    disabled={update.isPending}
                    onClick={() => update.mutate({ body: { ...draft } })}
                  >
                    {update.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                    {update.isPending ? t("saving") : t("common:save")}
                  </Button>
                </div>
              )}
              {/* Reacting is a read-level gesture — anyone who can see the
              notice can react to it — so this is offered to every reader,
              not only to whoever may edit. A notice with reactions turned
              off shows none. */}
              {post.reactions_enabled && (
                <ReactionBar
                  targetType={ReactionTarget.post}
                  targetId={post.id}
                  groups={post.reactions}
                />
              )}
              {post.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {post.tags.map((tag) => (
                    <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
                  ))}
                </div>
              )}
            </div>

            <div className="min-w-0 space-y-4">
              {/* The question, under what was said about it. Every reader sees
                it; only somebody who may edit the notice can change it, and
                they do that in the editor below rather than in place — a poll
                being answered and a poll being rewritten are different
                things on the same rows. */}
              {post.poll && pollDraft === null && <PostPoll post={post} />}
              {canEdit && (
                <div className="space-y-2">
                  {pollDraft === null ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setPollDraft(post.poll ? pollDraftFromRead(post.poll) : emptyPollDraft())
                      }
                      className="inline-flex items-center gap-2"
                    >
                      <Vote className="h-4 w-4" aria-hidden />
                      {post.poll ? t("poll.edit") : t("poll.add")}
                    </Button>
                  ) : (
                    <>
                      <PollEditor
                        idPrefix="post-poll"
                        value={pollDraft}
                        onChange={setPollDraft}
                        choicesLocked={pollAnswered}
                        anonymityLocked={pollAnswered && (post.poll?.is_anonymous ?? false)}
                        onRemove={post.poll ? () => removePoll.mutate() : undefined}
                      />
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" size="sm" onClick={() => setPollDraft(null)}>
                          {t("common:cancel")}
                        </Button>
                        <Button
                          size="sm"
                          disabled={savePoll.isPending || !isPollDraftValid(pollDraft)}
                          onClick={() => savePoll.mutate(pollDraftToWrite(pollDraft))}
                        >
                          {savePoll.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                          {savePoll.isPending ? t("saving") : t("common:save")}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              )}
              <ToolRelationsPanel
                tool={Tool.post}
                entity={post}
                canEdit={canEdit}
                entityTitle={post.name}
              />
            </div>
          </div>
        ) : (
          <Skeleton className="h-40 w-full" />
        )}

        {post != null && <ToolCommentsPanel tool={Tool.post} entity={post} />}

        <ConfirmDialog
          open={blocker.status === "blocked"}
          onOpenChange={(open) => {
            if (!open) blocker.reset?.();
          }}
          title={t("unsaved.title")}
          description={t("unsaved.body")}
          confirmLabel={t("unsaved.leave")}
          cancelLabel={t("unsaved.stay")}
          onConfirm={() => blocker.proceed?.()}
          destructive
        />
      </>
    </div>
  );
}
