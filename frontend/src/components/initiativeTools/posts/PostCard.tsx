import { Link } from "@tanstack/react-router";
import { CalendarClock, MessageSquare, Pin, PinOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type PostRead, ReactionTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PinnedBanner } from "@/components/initiativeTools/posts/PinnedBanner";
import { PostBody } from "@/components/initiativeTools/posts/PostBody";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { TagBadge } from "@/components/tags/TagBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSetPostPin, useUpdatePost } from "@/hooks/usePosts";
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
 */
export const PostCard = ({ post, canPin = false, className }: PostCardProps) => {
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

  const detailRoute = gp(toolDetailRoute(Tool.post, post.initiative_id, post.id));

  return (
    <Card
      className={cn(
        // The card is the post's surface — the editor inside it draws no box
        // of its own, so this is what the body sits on.
        "bg-card",
        post.is_pinned && "border-primary/40 bg-primary/[0.03]",
        // A draft reads as provisional rather than as another notice on the
        // board: it is the only card here nobody else can see.
        !post.is_published && "border-dashed",
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
        </div>
      </CardContent>
    </Card>
  );
};
