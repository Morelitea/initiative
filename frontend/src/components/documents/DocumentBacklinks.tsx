import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, FileText, Link2 } from "lucide-react";
import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useTranslation } from "react-i18next";

import { getDocumentBacklinks } from "@/api/documents";
import { useGuildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

interface DocumentBacklinksProps {
  documentId: number;
}

export function DocumentBacklinks({ documentId }: DocumentBacklinksProps) {
  const { t } = useTranslation("documents");
  const [isOpen, setIsOpen] = useState(true);
  const gp = useGuildPath();

  const {
    data: backlinks = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["documents", documentId, "backlinks"],
    queryFn: () => getDocumentBacklinks(documentId),
  });

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
            <Link2 className="text-muted-foreground h-4 w-4" />
            <span className="text-sm font-medium">
              {t("backlinks.title", { count: backlinks.length })}
            </span>
          </div>
          {isOpen ? (
            <ChevronDown className="text-muted-foreground h-4 w-4" />
          ) : (
            <ChevronRight className="text-muted-foreground h-4 w-4" />
          )}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t px-4 py-2">
          <ul className="space-y-1">
            {backlinks.map((backlink) => (
              <li key={backlink.id}>
                <Link
                  to={gp(`/documents/${backlink.id}`)}
                  className="group hover:bg-accent flex items-center gap-2 rounded-md px-2 py-1.5"
                >
                  <FileText className="text-muted-foreground h-4 w-4 shrink-0" />
                  <div className="flex-1 truncate">
                    <span className="text-sm group-hover:underline">{backlink.title}</span>
                    <span className="text-muted-foreground ml-2 text-xs">
                      {formatDistanceToNow(new Date(backlink.updated_at), { addSuffix: true })}
                    </span>
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
