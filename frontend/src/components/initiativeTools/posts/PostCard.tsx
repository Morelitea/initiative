import { Link } from "@tanstack/react-router";
import { CalendarClock, Eye, MailOpen, MessageSquare, Pin, PinOff } from "lucide-react";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

import { type PostRead, ReactionTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PinnedBanner } from "@/components/initiativeTools/posts/PinnedBanner";
import { PostBody } from "@/components/initiativeTools/posts/PostBody";
import { PostReadersDialog } from "@/components/initiativeTools/posts/PostReadersDialog";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { TagBadge } from "@/components/tags/TagBadge";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RelativeTime } from "@/components/ui/relative-time";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useMarkReadOnScreen, usePostReadTracker } from "@/hooks/usePostReadTracker";
import { useMarkPostUnread, useSetPostPin, useUpdatePost } from "@/hooks/usePosts";
import { toast } from "@/lib/chesterToast";
import { formatDateTime } from "@/lib/formatDate";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface PostCardProps {
  post: PostRead;
  /** Whether this reader may pin — guild admin or an initiative manager. The
   *  server decides again on the request; this only decides what is offered. */
  canPin?: boolean;
  className?: string;
}

/**
 * One notice on the board.
 *
 * The whole body is rendered, not a preview: a board is for reading, and a
 * notice that needs a click to be read is a notice nobody reads. The headline
 * links to the post's own page, which is where its comments and reactions live.
 *
 * A card only reaches a reader who may see the notice, so a scheduled one is
 * on the board of the people who wrote it and nobody else. It says so, and
 * offers the one thing there is to do about it: put it up now.
 *
 * Being on screen is what marks a notice read — a board is read by scrolling,
 * and asking somebody to click each one would be asking them to do the app's
 * bookkeeping. Marking it unread again puts it back and stops this card
 * counting it while they are still looking at it.
 */
const PostCardInner = ({ post, canPin = false, className }: PostCardProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const gp = useGuildPath();
  const setPin = useSetPostPin(post.id, {
    onSuccess: (updated) =>
      toast.success(updated.is_pinned ? t("pin.pinnedToast") : t("pin.unpinnedToast")),
  });

  // Clearing the schedule is what publishes: the same call the author would
  // make by editing, so there is no second route for "now".
  const publishNow = useUpdatePost(post.id, {
    onSuccess: () => toast.success(t("schedule.publishedToast")),
  });

  const { suppress } = usePostReadTracker();
  const cardRef = useMarkReadOnScreen(post.id, post.is_read);
  const markUnread = useMarkPostUnread({
    onSuccess: () => toast.success(t("read.markedUnread")),
  });
  const [readersOpen, setReadersOpen] = useState(false);

  const detailRoute = gp(toolDetailRoute(Tool.post, post.initiative_id, post.id));

  return (
    <Card
      ref={cardRef}
      className={cn(
        // The card is the post's surface — the editor inside it draws no box
        // of its own, so this is what the body sits on.
        "bg-card",
        post.is_pinned && "border-primary/40 bg-primary/[0.03]",
        // A draft reads as provisional rather than as another notice on the
        // board: it is the only card here nobody else can see.
        !post.is_published && "border-dashed",
        // Unread reads as "there is something here", which is a weight the
        // card carries rather than a badge it wears.
        !post.is_read && "border-primary/30 shadow-sm",
        className
      )}
    >
      <CardHeader className="gap-2 pb-3">
        <PinnedBanner post={post} canPin={canPin} />
        {!post.is_published && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
            <span className="inline-flex items-center gap-1.5">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden />
              {post.scheduled_for
                ? t("schedule.scheduledFor", { date: formatDateTime(post.scheduled_for) })
                : t("schedule.notPublished")}
            </span>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              disabled={publishNow.isPending}
              onClick={() => publishNow.mutate({ scheduled_for: null })}
            >
              {t("schedule.publishNow")}
            </Button>
          </div>
        )}
        {/* Signed, above the headline. A notice is somebody saying something,
            and a board that shows only what was said makes every notice read
            as the app's own announcement. */}
        {post.author ? (
          <div className="flex min-w-0 items-center gap-2">
            <ProfileAvatar
              user={post.author}
              decorations={post.author.profile_decorations}
              presence={post.author.presence}
              className="size-8 shrink-0"
            />
            <div className="min-w-0">
              <UserHandle
                user={post.author}
                className="font-medium text-sm"
                nameClassName="min-w-0 truncate"
              />
              <RelativeTime
                date={post.published_at ?? post.created_at}
                className="block text-muted-foreground text-xs"
              />
            </div>
          </div>
        ) : null}
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-lg leading-tight">
            <Link to={detailRoute} className="hover:underline">
              {post.name}
            </Link>
          </CardTitle>
          {canPin && (
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0"
              disabled={setPin.isPending}
              aria-label={post.is_pinned ? t("pin.unpin") : t("pin.pin")}
              onClick={() => setPin.mutate({ pinned: !post.is_pinned })}
            >
              {post.is_pinned ? (
                <PinOff className="h-4 w-4" aria-hidden />
              ) : (
                <Pin className="h-4 w-4" aria-hidden />
              )}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <PostBody body={post.body} />
        {post.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {post.tags.map((tag) => (
              <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {/* Reacting is a read-level gesture — anyone who can see the
              notice can react to it — so the bar is offered to every
              reader, not only to whoever may edit. */}
          <ReactionBar
            targetType={ReactionTarget.post}
            targetId={post.id}
            groups={post.reactions}
          />
          {/* The thread, from the board. A count says there is a conversation
              worth opening; nothing said so far is an invitation rather than a
              "0", which reads as an absence. Both land on the post, because the
              thread lives there. A post with comments turned off says neither —
              there is nothing to join. */}
          {post.comments_enabled && (
            <Link
              to={detailRoute}
              className="inline-flex items-center gap-1.5 text-muted-foreground text-sm hover:text-foreground hover:underline"
            >
              <MessageSquare className="h-4 w-4" aria-hidden />
              {post.comment_count > 0 ? t("comments", { count: post.comment_count }) : t("beFirst")}
            </Link>
          )}
          {/* Whether it landed, which is the point of saying it out loud.
              Offered to every reader, not just the author: they are all on the
              roster it opens, and they all put something on this board. */}
          {post.read_count > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-auto gap-1.5 px-2 py-1 text-muted-foreground text-xs"
              onClick={() => setReadersOpen(true)}
            >
              <Eye className="h-3.5 w-3.5" aria-hidden />
              {t("read.readBy", { count: post.read_count })}
            </Button>
          )}
          {/* Only once it has been read — on an unread notice this button
              would be a no-op wearing a label. */}
          {post.is_read && (
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto h-auto gap-1.5 px-2 py-1 text-muted-foreground text-xs"
              disabled={markUnread.isPending}
              onClick={() => {
                // Stop this card counting it again: it is still on screen, and
                // without this the observer would undo the click a beat later.
                suppress(post.id);
                markUnread.mutate(post.id);
              }}
            >
              <MailOpen className="h-3.5 w-3.5" aria-hidden />
              {t("read.markUnread")}
            </Button>
          )}
        </div>
      </CardContent>

      <PostReadersDialog open={readersOpen} onOpenChange={setReadersOpen} postId={post.id} />
    </Card>
  );
};

/**
 * Memoized, and that is load-bearing on a board rather than a micro-optimism.
 *
 * Reading marks notices read as you scroll, and each batch rewrites the cached
 * page — a new array holding the *same* row objects for everything it did not
 * touch. Without this, one row changing re-renders every mounted card, and
 * every card is a Lexical editor. With it, only the row that actually changed
 * re-renders.
 */
export const PostCard = memo(PostCardInner);
