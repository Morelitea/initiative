import { Link } from "react-router-dom";
import { formatDistanceToNow } from "date-fns";
import { ScrollText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { cn } from "@/lib/utils";
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
        "group block w-full overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-sm transition hover:-translate-y-0.5 hover:border-primary/50 hover:shadow-lg",
        className
      )}
      style={{ aspectRatio: "2 / 3" }}
    >
      <div className="relative aspect-square overflow-hidden border-b bg-muted">
        {document.featured_image_url ? (
          <img
            src={document.featured_image_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <ScrollText className="h-10 w-10 md:h-20 md:w-20" />
          </div>
        )}
        <div className="flex flex-col items-end gap-1 text-xs text-muted-foreground absolute bottom-2 right-2">
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
                  <h3 className="line-clamp-1 text-lg font-semibold leading-tight text-card-foreground">
                    {document.title}
                  </h3>
                </TooltipTrigger>
                <TooltipContent side="top" align="start">
                  <p>{document.title}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <p className="text-xs text-muted-foreground">
            Updated {formatDistanceToNow(new Date(document.updated_at), { addSuffix: true })}
          </p>
          {document.initiative && !hideInitiative ? (
            <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </div>
          ) : null}
        </div>
        <div className="mt-auto space-y-1 text-sm text-muted-foreground">
          {document.projects.length > 0 ? (
            <>
              <p className="text-xs font-medium text-foreground">
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
