import { useTranslation } from "react-i18next";

import type { DocumentSummary, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { SelectableGridItem } from "@/components/access/SelectableGridItem";
import { DocumentCard } from "@/components/documents/DocumentCard";
import { PaginationBar } from "@/components/PaginationBar";
import { TagBrowseLayout } from "@/components/tags/TagBrowseLayout";
import type { GridToggleOptions } from "@/hooks/useGridSelection";

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
  onToggleDocument?: (document: DocumentSummary, options?: GridToggleOptions) => void;
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
    <TagBrowseLayout
      allTags={allTags}
      tagCounts={tagCounts}
      untaggedCount={untaggedCount}
      selectedPaths={treeSelectedPaths}
      onToggleTag={onToggleTag}
    >
      {documents.length > 0 ? (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4">
            {documents.map((document) => (
              <SelectableGridItem
                key={document.id}
                active={selectionActive}
                selected={selectedDocumentIds?.has(document.id) ?? false}
                onToggle={(options) => onToggleDocument?.(document, options)}
                label={document.name}
              >
                <DocumentCard document={document} />
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
    </TagBrowseLayout>
  );
};
