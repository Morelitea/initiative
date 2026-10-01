import { useTranslation } from "react-i18next";

import { DocumentType, type Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolFilterPanel } from "@/components/initiativeTools/shared/ToolFilterPanel";
import { PropertyFilterParam } from "@/components/properties/PropertyFilter";
import { TagFilterPicker } from "@/components/tags/TagFilterPicker";
import type { ToolFilterFieldsProps } from "@/components/tools/ToolFilterFields";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** "All" is a sentinel: the underlying filter is absent, not a value. */
const ALL_DOCUMENT_TYPES = "all";

/** Order the types are offered in — native first, since it's the common case. */
const DOCUMENT_TYPE_OPTIONS = [
  { value: DocumentType.native, labelKey: "page.typeNative" },
  { value: DocumentType.file, labelKey: "page.typeFile" },
  { value: DocumentType.whiteboard, labelKey: "page.typeWhiteboard" },
  { value: DocumentType.spreadsheet, labelKey: "page.typeSpreadsheet" },
  { value: DocumentType.smart_link, labelKey: "page.typeSmartLink" },
] as const;

type DocumentFilterFieldsProps = ToolFilterFieldsProps<typeof Tool.document> & {
  /** Off where tags are browsed some other way (the tag tree). */
  tags?: boolean;
};

/** What the documents list narrows by: a search, tags, a type, and property
 *  conditions. */
export const DocumentFilterFields = ({
  value,
  onChange,
  initiativeId,
  tags = true,
  children,
}: DocumentFilterFieldsProps) => {
  const { t } = useTranslation(["documents", "tags"]);

  return (
    <>
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
            value={value.search ?? ""}
            onChange={(event) => onChange({ ...value, search: event.target.value })}
          />
        </div>
        {tags && (
          <div className="w-full space-y-2 sm:w-48">
            <Label
              htmlFor="document-tag-filter"
              className="block font-medium text-muted-foreground text-xs"
            >
              {t("page.filterByTag")}
            </Label>
            <TagFilterPicker
              id="document-tag-filter"
              tagIds={value.tag_ids ?? []}
              onChange={(tagIds) => onChange({ ...value, tag_ids: tagIds })}
              placeholder={t("page.allTags")}
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
            value={value.document_type ?? ALL_DOCUMENT_TYPES}
            onValueChange={(next) =>
              onChange({
                ...value,
                document_type: next === ALL_DOCUMENT_TYPES ? undefined : (next as DocumentType),
              })
            }
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
        {children}
      </div>
      <PropertyFilterParam
        value={value.property_filters}
        onChange={(next) => onChange({ ...value, property_filters: next })}
        initiativeId={initiativeId}
      />
    </>
  );
};

export interface DocumentsFilterBarProps extends DocumentFilterFieldsProps {
  filtersOpen: boolean;
  onFiltersOpenChange: (open: boolean) => void;
  /** How many filters are currently set — tells "Clear all" whether it has
   *  anything to do. */
  activeCount?: number;
  /** Resets search, tags, type, and property conditions — offered in the
   *  sheet. */
  onClear?: () => void;
}

export const DocumentsFilterBar = ({
  filtersOpen,
  onFiltersOpenChange,
  onClear,
  activeCount,
  ...fields
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
      <DocumentFilterFields {...fields} />
    </ToolFilterPanel>
  );
};
