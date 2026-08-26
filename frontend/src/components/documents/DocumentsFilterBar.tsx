import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { DocumentType } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import type { PropertyFilterCondition } from "@/components/properties/PropertyFilter";
import { PropertyFilter } from "@/components/properties/PropertyFilter";
import { TagPicker } from "@/components/tags/TagPicker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** "All" is a sentinel: the underlying filters are absent, not a value. */
export const ALL_DOCUMENT_TYPES = "all" as const;
export type DocumentTypeFilter = DocumentType | typeof ALL_DOCUMENT_TYPES;

/** Order the types are offered in — native first, since it's the common case. */
const DOCUMENT_TYPE_OPTIONS = [
  { value: DocumentType.native, labelKey: "page.typeNative" },
  { value: DocumentType.file, labelKey: "page.typeFile" },
  { value: DocumentType.whiteboard, labelKey: "page.typeWhiteboard" },
  { value: DocumentType.spreadsheet, labelKey: "page.typeSpreadsheet" },
  { value: DocumentType.smart_link, labelKey: "page.typeSmartLink" },
] as const;

export interface DocumentsFilterBarProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  viewMode: "grid" | "list" | "tags";
  tagFilters: TagSummary[];
  onTagFiltersChange: (tags: TagSummary[]) => void;
  fixedTagIds?: number[];
  documentTypeFilter: DocumentTypeFilter;
  onDocumentTypeFilterChange: (value: DocumentTypeFilter) => void;
  propertyFilters: PropertyFilterCondition[];
  onPropertyFiltersChange: (next: PropertyFilterCondition[]) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets search, tags, type, and property conditions — offered in the
   *  sheet. */
  onClear?: () => void;
}

export const DocumentsFilterBar = ({
  searchQuery,
  onSearchQueryChange,
  filtersOpen,
  onFiltersOpenChange,
  viewMode,
  tagFilters,
  onTagFiltersChange,
  fixedTagIds,
  documentTypeFilter,
  onDocumentTypeFilterChange,
  propertyFilters,
  onPropertyFiltersChange,
  onClear,
  activeCount,
}: DocumentsFilterBarProps) => {
  const { t } = useTranslation("documents");

  return (
    <ToolFilterPanel
      open={filtersOpen}
      onOpenChange={onFiltersOpenChange}
      title={t("page.filters")}
      onClear={onClear}
      activeCount={activeCount}
    >
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-full space-y-2 sm:flex-1">
          <Label
            htmlFor="document-search"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("page.searchLabel")}
          </Label>
          <Input
            id="document-search"
            type="search"
            placeholder={t("page.searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
          />
        </div>
        {viewMode !== "tags" && !fixedTagIds && (
          <div className="w-full space-y-2 sm:w-48">
            <Label
              htmlFor="document-tag-filter"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("page.filterByTag")}
            </Label>
            <TagPicker
              selectedTags={tagFilters}
              onChange={onTagFiltersChange}
              placeholder={t("page.allTags")}
              variant="filter"
            />
          </div>
        )}
        <div className="w-full space-y-2 sm:w-48">
          <Label
            htmlFor="document-type-filter"
            className="block font-medium text-muted-foreground text-xs"
          >
            {t("page.filterByType")}
          </Label>
          <Select
            value={documentTypeFilter}
            onValueChange={(value) => onDocumentTypeFilterChange(value as DocumentTypeFilter)}
          >
            <SelectTrigger id="document-type-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_DOCUMENT_TYPES}>{t("page.allTypes")}</SelectItem>
              {DOCUMENT_TYPE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {t(option.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <PropertyFilter value={propertyFilters} onChange={onPropertyFiltersChange} />
    </ToolFilterPanel>
  );
};
