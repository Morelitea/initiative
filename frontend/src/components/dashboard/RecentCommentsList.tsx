import { Link } from "@tanstack/react-router";
import { formatDistanceToNow, parseISO } from "date-fns";
import { MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { RecentActivityEntry } from "@/api/generated/initiativeAPI.schemas";
import { CommentContent } from "@/components/comments/CommentContent";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useGuildPath } from "@/lib/guildUrl";
import { getInitials } from "@/lib/initials";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getUserDisplayName } from "@/lib/userDisplay";

interface RecentCommentsListProps {
  comments: RecentActivityEntry[];
  isLoading?: boolean;
}

export function RecentCommentsList({ comments, isLoading }: RecentCommentsListProps) {
  const { t } = useTranslation("dashboard");
  const gp = useGuildPath();

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
              // biome-ignore lint/suspicious/noArrayIndexKey: This is a static list of skeleton loaders, so using the index as key is acceptable.
              <div key={i} className="flex gap-3">
                <Skeleton className="h-8 w-8 rounded-full" />
                <div className="flex-1 space-y-1">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-4 w-full" />
                </div>
              </div>
            ))}
          </div>
        ) : comments.length === 0 ? (
          <div className="flex h-50 items-center justify-center text-muted-foreground text-sm">
            <div className="flex flex-col items-center gap-2">
              <MessageSquare className="h-8 w-8 opacity-50" />
              <span>{t("recentComments.noComments")}</span>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {comments.map((entry) => {
              const linkTo = entry.task_id
                ? gp(`/tasks/${entry.task_id}`)
                : entry.document_id
                  ? gp(`/documents/${entry.document_id}`)
                  : undefined;

              const contextParts: string[] = [];
              if (entry.task_title) {
                contextParts.push(t("recentComments.onTask", { taskTitle: entry.task_title }));
              } else if (entry.document_title) {
                contextParts.push(
                  t("recentComments.onDocument", { documentTitle: entry.document_title })
                );
              }
              if (entry.project_name) {
                contextParts.push(
                  t("recentComments.inProject", { projectName: entry.project_name })
                );
              }

              const authorAvatarSrc =
                resolveUploadUrl(entry.author?.avatar_url) ||
                entry.author?.avatar_base64 ||
                undefined;
              const content = (
                <div key={entry.comment_id} className="flex gap-3">
                  <Avatar className="h-8 w-8 shrink-0">
                    {authorAvatarSrc ? <AvatarImage src={authorAvatarSrc} /> : null}
                    <AvatarFallback userId={entry.author?.id ?? null} className="text-xs">
                      {getInitials(entry.author?.full_name, entry.author?.email)}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="truncate font-medium text-sm">
                        {getUserDisplayName(entry.author, "Unknown")}
                      </span>
                      <span className="shrink-0 text-muted-foreground text-xs">
                        {formatDistanceToNow(parseISO(entry.created_at), { addSuffix: true })}
                      </span>
                    </div>
                    {contextParts.length > 0 && (
                      <p className="truncate text-muted-foreground text-xs">
                        {contextParts.join(" ")}
                      </p>
                    )}
                    <p className="mt-0.5 line-clamp-2 text-sm">
                      <CommentContent content={entry.content} />
                    </p>
                  </div>
                </div>
              );

              return linkTo ? (
                <Link
                  key={entry.comment_id}
                  to={linkTo}
                  className="block rounded-md p-2 transition-colors hover:bg-accent"
                >
                  {content}
                </Link>
              ) : (
                <div key={entry.comment_id} className="p-2">
                  {content}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
