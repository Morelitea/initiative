import { Link } from "@tanstack/react-router";
import { MessageSquare, Pin, PinOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import { type PostRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { PostBody } from "@/components/initiativeTools/posts/PostBody";
import { TagBadge } from "@/components/tags/TagBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useSetPostPin } from "@/hooks/usePosts";
import { toast } from "@/lib/chesterToast";
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
 */
export const PostCard = ({ post, canPin = false, className }: PostCardProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const gp = useGuildPath();
  const setPin = useSetPostPin(post.id, {
    onSuccess: (updated) =>
      toast.success(updated.is_pinned ? t("pin.pinnedToast") : t("pin.unpinnedToast")),
  });

  const pinnedUntil = post.is_pinned && post.pin_expires_at ? post.pin_expires_at : null;
  const detailRoute = gp(toolDetailRoute(Tool.post, post.initiative_id, post.id));

  return (
    <Card
      className={cn(
        // The card is the post's surface — the editor inside it draws no box
        // of its own, so this is what the body sits on.
        "bg-card",
        post.is_pinned && "border-primary/40 bg-primary/[0.03]",
        className
      )}
    >
      <CardHeader className="gap-2 pb-3">
        {post.is_pinned && (
          <div className="flex items-center gap-1.5 text-primary text-xs">
            <Pin className="h-3.5 w-3.5" aria-hidden />
            <span>
              {pinnedUntil
                ? t("pin.pinnedUntil", { date: new Date(pinnedUntil).toLocaleDateString() })
                : t("pin.pinnedBanner")}
            </span>
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
        {/* The thread, from the board. A count says there is a conversation
            worth opening; nothing said so far is an invitation rather than a
            "0", which reads as an absence. Both land on the post, because the
            thread lives there. A post with comments turned off says neither —
            there is nothing to join. */}
        {!post.comments_disabled && (
          <Link
            to={detailRoute}
            className="inline-flex items-center gap-1.5 text-muted-foreground text-sm hover:text-foreground hover:underline"
          >
            <MessageSquare className="h-4 w-4" aria-hidden />
            {post.comment_count > 0 ? t("comments", { count: post.comment_count }) : t("beFirst")}
          </Link>
        )}
      </CardContent>
    </Card>
  );
};
