import { ChevronDown, Tags } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagTreeView } from "@/components/tags/TagTreeView";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

interface TagBrowseLayoutProps {
  allTags: TagSummary[];
  tagCounts: Record<number, number>;
  /** Offers "Not tagged"; left off where the list cannot be narrowed to it. */
  untaggedCount?: number | null;
  selectedPaths: Set<string>;
  onToggleTag: (fullPath: string, ctrlKey: boolean) => void;
  /** What the picked tags narrow: the tool's own cards. */
  children: ReactNode;
}

/**
 * A list browsed by tag: the tag tree beside it on a wide screen, folded above
 * it on a phone. Every tool's tags view is this around its own cards.
 */
export const TagBrowseLayout = ({
  allTags,
  tagCounts,
  untaggedCount,
  selectedPaths,
  onToggleTag,
  children,
}: TagBrowseLayoutProps) => {
  const { t } = useTranslation("tags");
  const tree = (
    <TagTreeView
      tags={allTags}
      tagCounts={tagCounts}
      untaggedCount={untaggedCount}
      selectedTagPaths={selectedPaths}
      onToggleTag={onToggleTag}
    />
  );

  return (
    <div className="flex flex-col gap-4 md:flex-row">
      <Collapsible className="rounded-md border border-muted bg-background/40 md:hidden">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="group flex w-full items-center justify-between px-3 py-2 font-medium text-sm"
          >
            <span className="flex items-center gap-2">
              <Tags className="h-4 w-4" />
              {t("browseByTag")}
              {selectedPaths.size > 0 && (
                <Badge variant="secondary" className="ml-1 h-5 px-1.5 text-xs">
                  {selectedPaths.size}
                </Badge>
              )}
            </span>
            <ChevronDown className="h-4 w-4 transition-transform group-data-[state=open]:rotate-180" />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent className="overflow-hidden">
          <div className="max-h-64 overflow-y-auto overscroll-contain">{tree}</div>
        </CollapsibleContent>
      </Collapsible>
      <div className="hidden w-64 shrink-0 rounded-md border border-muted bg-background/40 md:block">
        {tree}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
};
