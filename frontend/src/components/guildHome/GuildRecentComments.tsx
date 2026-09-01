/**
 * The guild home's activity strip: the latest comments anywhere in the guild.
 *
 * It sits under the tool table and stays put while the rail switches tools —
 * the feed is guild-wide, not a view of the selected tool. The endpoint only
 * returns comments on entities the user may see, so no filtering happens here.
 */

import { Link } from "@tanstack/react-router";
import { MessageSquare } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  ReactionTarget,
  type RecentActivityEntry,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentContent } from "@/components/comments/CommentContent";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RelativeTime } from "@/components/ui/relative-time";
import { Skeleton } from "@/components/ui/skeleton";
import { useRecentComments } from "@/hooks/useComments";
import { useGuildPath } from "@/lib/guildUrl";
import { entityRefRoute, TOOLS, taskRoute, toolDetailRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getInitialsForUser, getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

const RECENT_COMMENTS_PARAMS = { limit: 10 };

/**
 * Reports whether an element's content overflows the lines it is clamped to.
 *
 * Only measured while collapsed — expanding removes the clamp, which would
 * otherwise read back as "not truncated" and retract the control that just
 * expanded it.
 */
const useIsTruncated = (ref: React.RefObject<HTMLElement | null>, collapsed: boolean) => {
  const [isTruncated, setIsTruncated] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || !collapsed) return;

    const measure = () => setIsTruncated(element.scrollHeight > element.clientHeight + 1);
    measure();

    // The clamp follows the column's width, so a resize can change the answer.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, collapsed]);

  return isTruncated;
};

const CommentEntry = ({ entry }: { entry: RecentActivityEntry }) => {
  const { t } = useTranslation(["guildHome", "comments"]);
  const gp = useGuildPath();
  const contentRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const isTruncated = useIsTruncated(contentRef, !expanded);

  // A null initiative names a guild-level address, which the route builders
  // handle; the task/document columns are the older shape of the same parent.
  const initiativeId = entry.initiative_id ?? null;
  const tool = TOOLS.find((candidate) => candidate === entry.entity_type) ?? null;
  const taskId = entry.entity_type === "task" ? entry.entity_id : entry.task_id;

  let linkTo: string | undefined;
  if (taskId) {
    linkTo = gp(
      entry.project_id != null
        ? taskRoute(initiativeId, entry.project_id, taskId)
        : entityRefRoute("task", taskId)
    );
  } else if (tool && entry.entity_id) {
    linkTo = gp(toolDetailRoute(tool, initiativeId, entry.entity_id));
  } else if (entry.document_id) {
    linkTo = gp(toolDetailRoute(Tool.document, initiativeId, entry.document_id));
  }

  const contextParts: string[] = [];
  if (entry.task_title) {
    contextParts.push(t("recentComments.onTask", { taskTitle: entry.task_title }));
  } else if (entry.document_name) {
    contextParts.push(t("recentComments.onDocument", { documentTitle: entry.document_name }));
  } else if (entry.entity_name) {
    contextParts.push(t("recentComments.onEntity", { entityName: entry.entity_name }));
  }
  // A comment on the project itself already names it, so it isn't also "in" it.
  if (entry.project_name && entry.entity_type !== Tool.project) {
    contextParts.push(t("recentComments.inProject", { projectName: entry.project_name }));
  }

  const authorAvatarSrc = resolveUploadUrl(entry.author?.avatar_url) || undefined;

  const body = (
    <div className="flex gap-3">
      <Avatar className="h-8 w-8 shrink-0">
        {authorAvatarSrc ? <AvatarImage src={authorAvatarSrc} /> : null}
        <AvatarFallback userId={entry.author?.id ?? null} className="text-xs">
          {getInitialsForUser(entry.author)}
        </AvatarFallback>
      </Avatar>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium text-sm">
            {getUserDisplayName(entry.author, t("recentComments.unknownAuthor"))}
          </span>
          <RelativeTime
            date={entry.created_at}
            className="shrink-0 text-muted-foreground text-xs"
          />
        </div>
        {contextParts.length > 0 && (
          <p className="truncate text-muted-foreground text-xs">{contextParts.join(" ")}</p>
        )}
        <CommentContent
          ref={contentRef}
          content={entry.content}
          compact
          // The preview is itself a link, so the body must not hold one.
          disableLinks
          className={cn("mt-0.5", !expanded && "line-clamp-2")}
        />
      </div>
    </div>
  );

  return (
    <div className={cn("rounded-md p-2 transition-colors", linkTo && "hover:bg-accent")}>
      {linkTo ? (
        <Link to={linkTo} className="block">
          {body}
        </Link>
      ) : (
        body
      )}
      {/* Outside the link above: a button nested in one is neither valid nor
          clickable without fighting the navigation. The indent lines it up
          with the comment body, past the avatar. */}
      {(isTruncated || expanded) && (
        <button
          type="button"
          className="mt-1 ml-11 font-medium text-primary text-xs hover:underline"
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? t("recentComments.showLess") : t("recentComments.readMore")}
        </button>
      )}
      {/* Read-only here, and also outside the link: the feed shows how a
          comment landed, and reacting to one belongs in the thread it is in —
          which is exactly where the row already goes. */}
      {entry.reactions?.length ? (
        <ReactionBar
          className="mt-1 ml-11"
          targetType={ReactionTarget.comment}
          targetId={entry.comment_id}
          groups={entry.reactions}
          canReact={false}
        />
      ) : null}
    </div>
  );
};

export const GuildRecentComments = () => {
  const { t } = useTranslation(["guildHome", "comments"]);
  const { data: comments, isLoading, isError } = useRecentComments(RECENT_COMMENTS_PARAMS);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("recentComments.title")}</CardTitle>
        <CardDescription>{t("recentComments.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
              <div key={i} className="flex gap-3">
                <Skeleton className="h-8 w-8 rounded-full" />
                <div className="flex-1 space-y-1">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-4 w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : isError ? (
          <p className="text-destructive text-sm">{t("recentComments.loadError")}</p>
        ) : !comments || comments.length === 0 ? (
          <div className="flex h-50 items-center justify-center text-muted-foreground text-sm">
            <div className="flex flex-col items-center gap-2">
              <MessageSquare className="h-8 w-8 opacity-50" />
              <span>{t("recentComments.noComments")}</span>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {comments.map((entry) => (
              <CommentEntry key={entry.comment_id} entry={entry} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
