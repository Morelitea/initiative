import { Link } from "@tanstack/react-router";
import { BookText } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool, type WikiSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagBadge } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface WikiCardProps {
  wiki: WikiSummary;
  className?: string;
}

/**
 * One wiki in a list of them.
 *
 * Led by its name and what it covers rather than by a picture: a wiki is told
 * apart by its subject, and the one number worth showing from outside is how
 * many pages are in it — which is the difference between a handbook somebody
 * started and one the team actually keeps.
 */
export const WikiCard = ({ wiki, className }: WikiCardProps) => {
  const { t } = useTranslation("wikis");
  const gp = useGuildPath();
  const relativeUpdatedAt = useRelativeTime(wiki.updated_at);
  const commentCount = wiki.comments_enabled ? (wiki.comment_count ?? 0) : null;

  return (
    <Link
      to={gp(toolDetailRoute(Tool.wiki, wiki.initiative_id, wiki.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
    >
      <div className="flex items-start gap-3 p-4">
        <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground transition group-hover:text-foreground">
          <BookText className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
            {wiki.name}
          </h3>
          {wiki.description ? (
            <p className="line-clamp-2 text-muted-foreground text-sm">{wiki.description}</p>
          ) : null}
          <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
            <Badge variant="secondary">{t("pageCount", { count: wiki.page_count })}</Badge>
            {commentCount !== null && commentCount > 0 && (
              <Badge variant="secondary">{t("card.comments", { count: commentCount })}</Badge>
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            {t("card.updated", { date: relativeUpdatedAt })}
          </p>
          {wiki.tags.length > 0 ? (
            <div className="flex flex-wrap gap-1 pt-1">
              {wiki.tags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} nested />
              ))}
              {wiki.tags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{wiki.tags.length - 3}</span>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </Link>
  );
};
