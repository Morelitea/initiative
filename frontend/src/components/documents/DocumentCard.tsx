import { Link } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import { ScrollText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { cn } from "@/lib/utils";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import type { DocumentSummary } from "@/types/api";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface DocumentCardProps {
  document: DocumentSummary;
  className?: string;
  hideInitiative?: boolean;
}

export const DocumentCard = ({ document, className, hideInitiative }: DocumentCardProps) => {
  const projectCount = document.projects.length;
  const commentCount = document.comment_count ?? 0;

  return (
    <Link
      to={`/documents/${document.id}`}
      className={cn(
        "group bg-card text-card-foreground hover:border-primary/50 block w-full overflow-hidden rounded-2xl border shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg",
        className
      )}
      style={{ aspectRatio: "2 / 3" }}
    >
      <div className="bg-muted relative aspect-square overflow-hidden border-b">
        {document.featured_image_url ? (
          <img
            src={resolveUploadUrl(document.featured_image_url) ?? undefined}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="text-muted-foreground flex h-full items-center justify-center">
            <ScrollText className="h-10 w-10 md:h-20 md:w-20" />
          </div>
        )}
        <div className="text-muted-foreground absolute right-2 bottom-2 flex flex-col items-end gap-1 text-xs">
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
              to={`/initiatives/${document.initiative.id}`}
              className="text-muted-foreground inline-flex items-center gap-2 text-sm"
            >
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </Link>
          ) : null}
        </div>
        <div className="text-muted-foreground mt-auto space-y-1 text-sm">
          {document.projects.length > 0 ? (
            <>
              <p className="text-foreground text-xs font-medium">
                Linked to {document.projects.length} project
                {document.projects.length === 1 ? "" : "s"}
              </p>
              <div className="line-clamp-2 text-xs">
                {document.projects
                  .map((project) => project.project_name ?? `Project #${project.project_id}`)
                  .join(", ")}
              </div>
            </>
          ) : (
            <p className="text-xs">Not attached to any projects yet.</p>
          )}
        </div>
      </div>
    </Link>
  );
};
