import { ChevronDown, Tags } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DocumentSummary, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { PaginationBar } from "@/components/documents/PaginationBar";
import { TagTreeView } from "@/components/tags/TagTreeView";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

export interface DocumentsTagsViewProps {
  documents: DocumentSummary[];
  allTags: TagSummary[];
  tagCounts: Record<number, number>;
  untaggedCount: number;
  treeSelectedPaths: Set<string>;
  onToggleTag: (fullPath: string, ctrlKey: boolean) => void;
  page: number;
  pageSize: number;
  totalCount: number;
  hasNext: boolean;
  onPageChange: (updater: number | ((prev: number) => number)) => void;
  onPageSizeChange: (size: number) => void;
  onPrefetchPage: (page: number) => void;
  /** Bulk-selection mode (owned by the page, shared with the other views):
   * cards become checkboxes while active. */
  selectionActive?: boolean;
  selectedDocumentIds?: Set<number>;
  onToggleDocument?: (document: DocumentSummary) => void;
}

export const DocumentsTagsView = ({
  documents,
  allTags,
  tagCounts,
  untaggedCount,
  treeSelectedPaths,
  onToggleTag,
  page,
  pageSize,
  totalCount,
  hasNext,
  onPageChange,
  onPageSizeChange,
  onPrefetchPage,
  selectionActive = false,
  selectedDocumentIds,
  onToggleDocument,
}: DocumentsTagsViewProps) => {
  const { t } = useTranslation("documents");

  return (
    <div className="flex flex-col gap-4 md:flex-row">
      {/* Mobile: collapsible tag panel */}
      <Collapsible className="rounded-md border border-muted bg-background/40 md:hidden">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center justify-between px-3 py-2 font-medium text-sm"
          >
            <span className="flex items-center gap-2">
              <Tags className="h-4 w-4" />
              {t("page.browseByTag")}
              {treeSelectedPaths.size > 0 && (
                <Badge variant="secondary" className="ml-1 h-5 px-1.5 text-xs">
                  {treeSelectedPaths.size}
                </Badge>
              )}
            </span>
            <ChevronDown className="h-4 w-4" />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="max-h-64">
            <TagTreeView
              tags={allTags}
              tagCounts={tagCounts}
              untaggedCount={untaggedCount}
              selectedTagPaths={treeSelectedPaths}
              onToggleTag={onToggleTag}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>
      {/* Desktop: fixed sidebar */}
      <div className="hidden w-64 shrink-0 rounded-md border border-muted bg-background/40 md:block">
        <TagTreeView
          tags={allTags}
          tagCounts={tagCounts}
          untaggedCount={untaggedCount}
          selectedTagPaths={treeSelectedPaths}
          onToggleTag={onToggleTag}
        />
      </div>
      <div className="min-w-0 flex-1">
        {documents.length > 0 ? (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
              {documents.map((document) => (
                <SelectableGridItem
                  key={document.id}
                  active={selectionActive}
                  selected={selectedDocumentIds?.has(document.id) ?? false}
                  onToggle={() => onToggleDocument?.(document)}
                  label={document.title}
                >
                  <DocumentCard document={document} hideInitiative />
                </SelectableGridItem>
              ))}
            </div>
            {totalCount > 0 && (
              <div className="mt-4">
                <PaginationBar
                  page={page}
                  pageSize={pageSize}
                  totalCount={totalCount}
                  hasNext={hasNext}
                  onPageChange={onPageChange}
                  onPageSizeChange={onPageSizeChange}
                  onPrefetchPage={onPrefetchPage}
                />
              </div>
            )}
          </>
        ) : (
          <div className="py-8 text-center text-muted-foreground text-sm">
            {t("page.noMatchingTags")}
          </div>
        )}
      </div>
    </div>
  );
};
