import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { type DocumentSummary, Tool } from "@/api/generated/initiativeAPI.schemas";
import { UnreadDot } from "@/components/notifications/UnreadDot";
import { PropertyValueCell } from "@/components/properties/PropertyValueCell";
import { nonEmptyPropertySummaries } from "@/components/properties/propertyHelpers";
import { LazyImage } from "@/components/shared/LazyImage";
import { TagBadge } from "@/components/tags/TagBadge";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useUnreadTree } from "@/hooks/useUnreadTree";
import { documentIcon } from "@/lib/documentIcon";
import { getFileTypeLabel } from "@/lib/fileUtils";
import { useGuildPath } from "@/lib/guildUrl";
import { matchSmartLinkProvider } from "@/lib/smartLinkProviders";
import { toolDetailRoute } from "@/lib/tools";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { cn } from "@/lib/utils";

interface DocumentCardProps {
  document: DocumentSummary;
  className?: string;
}

export const DocumentCard = ({ document, className }: DocumentCardProps) => {
  const { t } = useTranslation("documents");
  const relativeUpdatedAt = useRelativeTime(document.updated_at);
  const gp = useGuildPath();
  const unread = useUnreadTree();
  // A document with comments off shows no thread anywhere, so it shows no count.
  const commentCount = document.comments_enabled ? (document.comment_count ?? 0) : null;
  const isFileDocument = document.document_type === "file";
  const fileTypeLabel = isFileDocument
    ? getFileTypeLabel(document.file_content_type, document.original_filename)
    : null;

  // The mark this document draws, by what sort of document it is — shared with
  // the relations card so the two cannot drift apart.
  const { Icon: FileIcon, colorClass: fileIconColor } = documentIcon({
    document_type: document.document_type,
    mime_type: document.file_content_type,
    original_filename: document.original_filename,
    smart_link_url: document.smart_link_url,
  });
  const smartLinkMatch =
    document.document_type === "smart_link" && document.smart_link_url
      ? matchSmartLinkProvider(document.smart_link_url)
      : null;

  return (
    <Link
      to={gp(toolDetailRoute(Tool.document, document.initiative_id, document.id))}
      className={cn(
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
      // style={{ aspectRatio: "2 / 3" }}
    >
      {/* Squarer thumbnails cost a phone most of a card each while showing, for
          the usual document, one centred icon. Shorter below `sm`. */}
      <div className="relative aspect-4/3 overflow-hidden border-b bg-muted sm:aspect-square">
        {document.featured_image_url ? (
          <LazyImage
            src={resolveUploadUrl(document.featured_image_url)}
            alt=""
            className="h-full w-full"
            imgClassName="transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <FileIcon
              className={cn(
                "h-10 w-10 md:h-20 md:w-20 lg:h-24 lg:w-24 xl:h-28 xl:w-28",
                fileIconColor
              )}
            />
          </div>
        )}
        <div className="absolute right-2 bottom-2 flex flex-col items-end gap-1 text-muted-foreground text-xs">
          {isFileDocument && fileTypeLabel ? (
            <Badge variant="secondary">{fileTypeLabel}</Badge>
          ) : null}
          {document.document_type === "whiteboard" ? (
            <Badge variant="secondary">{t("card.whiteboardLabel")}</Badge>
          ) : null}
          {document.document_type === "spreadsheet" ? (
            <Badge variant="secondary">{t("card.spreadsheetLabel")}</Badge>
          ) : null}
          {smartLinkMatch ? <Badge variant="secondary">{smartLinkMatch.label}</Badge> : null}
          {document.is_template ? <Badge variant="outline">{t("card.template")}</Badge> : null}
          {commentCount !== null && (
            <Badge variant="secondary">{t("card.comments", { count: commentCount })}</Badge>
          )}
        </div>
      </div>
      <div className="flex h-full flex-col gap-3 p-4">
        <div className="space-y-1">
          <div className="flex items-start justify-between gap-2">
            <TooltipProvider delayDuration={300}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <h3 className="line-clamp-1 font-semibold text-card-foreground text-lg leading-tight">
                    {document.name}
                  </h3>
                </TooltipTrigger>
                <TooltipContent side="top" align="start">
                  <p>{document.name}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
            {unread.hasResource(document.guild_id, Tool.document, document.id) ? (
              <UnreadDot className="mt-2" />
            ) : null}
          </div>
          <p className="text-muted-foreground text-xs">
            {t("card.updated", { date: relativeUpdatedAt })}
          </p>
          {document.tags && document.tags.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {document.tags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} nested />
              ))}
              {document.tags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{document.tags.length - 3}</span>
              )}
            </div>
          ) : null}
          {(() => {
            const propertyChips = nonEmptyPropertySummaries(document.properties);
            if (propertyChips.length === 0) return null;
            return (
              <div className="flex flex-wrap gap-1">
                {propertyChips.map((summary) => (
                  <PropertyValueCell
                    key={summary.property_id}
                    summary={summary}
                    variant="chip"
                    nested
                  />
                ))}
              </div>
            );
          })()}
        </div>
      </div>
    </Link>
  );
};
