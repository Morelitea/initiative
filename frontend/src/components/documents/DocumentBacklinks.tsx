import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, FileText, Link2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { RelativeTime } from "@/components/ui/relative-time";
import { useReferencedBy } from "@/hooks/useRelationships";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

interface DocumentBacklinksProps {
  documentId: number;
}

export function DocumentBacklinks({ documentId }: DocumentBacklinksProps) {
  const { t } = useTranslation("documents");
  const [isOpen, setIsOpen] = useState(true);
  const gp = useGuildPath();

  const {
    data: links = [],
    isLoading,
    isError,
  } = useReferencedBy(
    { type: SearchEntityType.document, id: documentId },
    SearchEntityType.document
  );

  // Most recently touched first, the way a list of pages is read. The edges
  // come back in the order they were made, which is the order somebody typed
  // the links rather than anything a reader cares about.
  const backlinks = [...links].sort((a, b) =>
    (b.other.updated_at ?? "").localeCompare(a.other.updated_at ?? "")
  );

  if (isLoading) {
    return null;
  }

  if (isError) {
    return null;
  }

  // Don't show section if no backlinks
  if (backlinks.length === 0) {
    return null;
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="rounded-lg border">
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="flex w-full items-center justify-between px-4 py-3 hover:bg-transparent"
        >
          <div className="flex items-center gap-2">
            <Link2 className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium text-sm">
              {t("backlinks.title", { count: backlinks.length })}
            </span>
          </div>
          {isOpen ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t px-4 py-2">
          <ul className="space-y-1">
            {backlinks.map(({ id, other }) => (
              <li key={id}>
                <Link
                  to={gp(toolDetailRoute(Tool.document, other.initiative_id, other.id))}
                  className="group flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent"
                >
                  <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 truncate">
                    <span className="text-sm group-hover:underline">{other.title}</span>
                    {other.updated_at && (
                      <RelativeTime
                        date={other.updated_at}
                        className="ml-2 text-muted-foreground text-xs"
                      />
                    )}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
