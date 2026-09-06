import { Link, useBlocker, useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import {
  CalendarClock,
  ListChecks,
  Loader2,
  Pin,
  PinOff,
  SearchX,
  Settings,
  ShieldAlert,
} from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ReactionTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { PinnedBanner } from "@/components/initiativeTools/posts/PinnedBanner";
import {
  emptyPollDraft,
  isPollDraftValid,
  type PollDraft,
  PollEditor,
  pollDraftFromRead,
  pollDraftToWrite,
} from "@/components/initiativeTools/posts/PollEditor";
import { PostPoll } from "@/components/initiativeTools/posts/PostPoll";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { StatusMessage } from "@/components/StatusMessage";
import { TagBadge } from "@/components/tags/TagBadge";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { RelativeTime } from "@/components/ui/relative-time";
import { Skeleton } from "@/components/ui/skeleton";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import {
  useDeletePostPoll,
  usePost,
  useSetPostPin,
  useSetPostPoll,
  useUpdatePost,
} from "@/hooks/usePosts";
import { useRecordRecentView } from "@/hooks/useRecents";
import { toast } from "@/lib/chesterToast";
import { getHttpStatus } from "@/lib/errorMessage";
import { formatDateTime, fromLocalDateTimeInput, toLocalDateTimeInput } from "@/lib/formatDate";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { hasBody, MAX_POST_TEXT_CHARS } from "@/lib/posts";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
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
  const { guildId, postId } = useParams({ strict: false }) as {
    guildId: string;
    postId: string;
  };
  const parsedId = Number(postId);
  const gp = useGuildPath();

  const postQuery = usePost(Number.isFinite(parsedId) ? parsedId : null);
  const post = postQuery.data;
  const initiativeId = useCanonicalInitiativeId(post?.initiative_id);

  const recordViewMutation = useRecordRecentView("post", Number(guildId));
  const viewedPostId = post?.id;
  useEffect(() => {
    if (!viewedPostId) return;
    recordViewMutation.mutate(viewedPostId);
  }, [viewedPostId, recordViewMutation.mutate]);

  const canEdit = hasWriteAccess(post?.my_permission_level);

  const initiativeQuery = useInitiative(post?.initiative_id ?? null);
  const { canManage } = useInitiativeAccess();
  const canPin = initiativeQuery.data ? canManage(initiativeQuery.data) : false;

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
  const setPin = useSetPostPin(parsedId, {
    onSuccess: (updated) =>
      toast.success(updated.is_pinned ? t("pin.pinnedToast") : t("pin.unpinnedToast")),
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
  // Answered polls keep their choices and their anonymity; the server refuses
  // to change either, and the editor stops offering it rather than letting
  // somebody type an edit that will be rejected.
  const pollAnswered = (post?.poll?.total_voters ?? 0) > 0 || (post?.poll?.has_voted ?? false);

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

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (postQuery.isError) {
    const status = getHttpStatus(postQuery.error);
    const backTo = gp(toolListRoute(Tool.post, initiativeId));
    const backLabel = t("backToPosts");

    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("noAccess")}
          description={t("noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("notFound")}
        description={t("notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <ToolBreadcrumb
        tool={Tool.post}
        initiativeId={post?.initiative_id}
        trail={[{ label: post ? post.name : <Skeleton className="h-4 w-32" /> }]}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          {post ? (
            <h1 className="font-semibold text-3xl tracking-tight">{post.name}</h1>
          ) : (
            <Skeleton className="h-9 w-64" />
          )}
          {/* Signed, the way the board signs it. A notice is somebody saying
              something, and its own page is the last place that should be
              left off. Under the headline here rather than above it, because
              on a page the title comes first and the byline answers it. */}
          {post?.author ? (
            <div className="flex min-w-0 items-center gap-2 pt-1">
              <ProfileAvatar
                user={post.author}
                decorations={post.author.profile_decorations}
                presence={post.author.presence}
                className="size-7 shrink-0"
              />
              <UserHandle user={post.author} className="text-sm" nameClassName="min-w-0 truncate" />
              <span aria-hidden className="text-muted-foreground text-xs">
                ·
              </span>
              <RelativeTime
                date={post.published_at ?? post.created_at}
                className="text-muted-foreground text-xs"
              />
            </div>
          ) : null}
          {post && <PinnedBanner post={post} canPin={canPin} />}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {post && canPin && (
            <Button
              variant="outline"
              size="sm"
              disabled={setPin.isPending}
              onClick={() => setPin.mutate({ pinned: !post.is_pinned })}
              className="inline-flex items-center gap-2"
            >
              {post.is_pinned ? (
                <PinOff className="h-4 w-4" aria-hidden />
              ) : (
                <Pin className="h-4 w-4" aria-hidden />
              )}
              {post.is_pinned ? t("pin.unpin") : t("pin.pin")}
            </Button>
          )}
          {post && canEdit && (
            <Button variant="outline" size="sm" asChild>
              <Link
                to={gp(toolSettingsRoute(Tool.post, initiativeId, post.id))}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" aria-hidden />
                {t("common:toolSettings.title")}
              </Link>
            </Button>
          )}
        </div>
      </div>

      {/* Reaching this page at all means being able to see the notice, and a
          draft answers 404 to everyone who cannot edit it — so this strip is
          only ever in front of someone who can act on it. It says the state
          and offers the two things there are to do: move the time, or put it
          up now. */}
      {post && !post.is_published && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-dashed p-3">
          <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
            <CalendarClock className="h-4 w-4" aria-hidden />
            {post.scheduled_for
              ? t("schedule.scheduledFor", { date: formatDateTime(post.scheduled_for) })
              : t("schedule.notPublished")}
          </p>
          {canEdit && (
            <div className="flex flex-wrap items-center gap-2">
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
                disabled={reschedule.isPending}
                onClick={() => reschedule.mutate({ scheduled_for: null })}
              >
                {t("schedule.publishNow")}
              </Button>
            </div>
          )}
        </div>
      )}

      {post ? (
        <div className="space-y-3">
          <Suspense fallback={<Skeleton className="h-40 w-full" />}>
            <Editor
              key={post.id}
              // An empty object is not an empty editor state — Lexical refuses
              // one whose root has no children, and a notice that is only a
              // headline and a poll stores exactly that. Passing nothing lets
              // the editor build its own empty document.
              editorSerializedState={
                hasBody(post.body) ? (post.body as unknown as SerializedEditorState) : undefined
              }
              onSerializedChange={setDraft}
              readOnly={!canEdit}
              showToolbar={canEdit}
              initiativeId={post.initiative_id}
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
                onClick={() => update.mutate({ body: draft as unknown as Record<string, unknown> })}
              >
                {update.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                {update.isPending ? t("saving") : t("common:save")}
              </Button>
            </div>
          )}
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
                  <ListChecks className="h-4 w-4" aria-hidden />
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
          {/* Reacting is a read-level gesture — anyone who can see the
              notice can react to it — so this is offered to every reader,
              not only to whoever may edit. */}
          <ReactionBar
            targetType={ReactionTarget.post}
            targetId={post.id}
            groups={post.reactions}
          />
          {post.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {post.tags.map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <Skeleton className="h-40 w-full" />
      )}

      {post != null && <ToolCommentsPanel tool={Tool.post} entity={post} canModerate={canEdit} />}

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
    </div>
  );
}
