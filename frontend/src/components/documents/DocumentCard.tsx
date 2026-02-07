import { Link } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import { FileSpreadsheet, FileText, Presentation, ScrollText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useGuildPath } from "@/lib/guildUrl";
import { TagBadge } from "@/components/tags/TagBadge";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { cn } from "@/lib/utils";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getFileTypeLabel } from "@/lib/fileUtils";
import type { DocumentSummary } from "@/types/api";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface DocumentCardProps {
  document: DocumentSummary;
  className?: string;
  hideInitiative?: boolean;
}

export const DocumentCard = ({ document, className, hideInitiative }: DocumentCardProps) => {
  const gp = useGuildPath();
  const projectCount = document.projects.length;
  const commentCount = document.comment_count ?? 0;
  const isFileDocument = document.document_type === "file";
  const fileTypeLabel = isFileDocument
    ? getFileTypeLabel(document.file_content_type, document.original_filename)
    : null;

  // Get the appropriate icon for file documents
  const FileIcon =
    fileTypeLabel === "Excel"
      ? FileSpreadsheet
      : fileTypeLabel === "PowerPoint"
        ? Presentation
        : FileText;

  return (
    <Link
      to={gp(`/documents/${document.id}`)}
      className={cn(
        "group bg-card text-card-foreground hover:border-primary/50 block w-full overflow-hidden rounded-2xl border shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg",
        className
      )}
      // style={{ aspectRatio: "2 / 3" }}
    >
      <div className="bg-muted relative aspect-square overflow-hidden border-b">
        {document.featured_image_url ? (
          <img
            src={resolveUploadUrl(document.featured_image_url) ?? undefined}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : isFileDocument ? (
          <div className="flex h-full items-center justify-center">
            <FileIcon
              className={cn(
                "h-10 w-10 md:h-20 md:w-20",
                fileTypeLabel === "PDF" && "text-red-500",
                fileTypeLabel === "Word" && "text-blue-600",
                fileTypeLabel === "Excel" && "text-green-600",
                fileTypeLabel === "PowerPoint" && "text-orange-500",
                fileTypeLabel === "Text" && "text-gray-500",
                fileTypeLabel === "HTML" && "text-purple-500"
              )}
            />
          </div>
        ) : (
          <div className="text-muted-foreground flex h-full items-center justify-center">
            <ScrollText className="h-10 w-10 md:h-20 md:w-20" />
          </div>
        )}
        <div className="text-muted-foreground absolute right-2 bottom-2 flex flex-col items-end gap-1 text-xs">
          {isFileDocument && fileTypeLabel ? (
            <Badge variant="secondary">{fileTypeLabel}</Badge>
          ) : null}
          {document.is_template ? <Badge variant="outline">Template</Badge> : null}
          <Badge variant="secondary">
            {projectCount} project{projectCount === 1 ? "" : "s"}
          </Badge>
          <Badge variant="secondary">
            {commentCount} comment{commentCount === 1 ? "" : "s"}
          </Badge>
        </div>
      </div>
      <div className="flex h-full flex-col gap-3 p-4">
        <div className="space-y-1">
          <div className="flex items-start justify-between gap-2">
            <TooltipProvider delayDuration={300}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <h3 className="text-card-foreground line-clamp-1 text-lg leading-tight font-semibold">
                    {document.title}
                  </h3>
                </TooltipTrigger>
                <TooltipContent side="top" align="start">
                  <p>{document.title}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <p className="text-muted-foreground text-xs">
            Updated {formatDistanceToNow(new Date(document.updated_at), { addSuffix: true })}
          </p>
          {document.initiative && !hideInitiative ? (
            <Link
              to={gp(`/initiatives/${document.initiative.id}`)}
              className="text-muted-foreground inline-flex items-center gap-2 text-sm"
            >
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </Link>
          ) : null}
          {document.tags && document.tags.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {document.tags.slice(0, 3).map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
              {document.tags.length > 3 && (
                <span className="text-muted-foreground text-xs">+{document.tags.length - 3}</span>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </Link>
  );
};
