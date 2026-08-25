import { LayoutTemplate } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { TOOL_ICONS } from "@/lib/tools";

export const DOCUMENT_STATUSES = ["documents", "templates"] as const;

export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];

export const isDocumentStatus = (value: unknown): value is DocumentStatus =>
  typeof value === "string" && (DOCUMENT_STATUSES as readonly string[]).includes(value);

const STATUS_ICONS = {
  documents: TOOL_ICONS[Tool.document],
  templates: LayoutTemplate,
} as const;

type DocumentsStatusFilterProps = {
  value: DocumentStatus;
  onChange: (value: DocumentStatus) => void;
  /** Per-state totals; a state whose count hasn't loaded just shows no badge. */
  counts?: Partial<Record<DocumentStatus, number | undefined>>;
};

/**
 * Which documents the list is showing. Templates are a state of the same list
 * rather than a separate destination — same cards, filters, and bulk actions —
 * so this sits beside the list the way the projects list splits its own
 * templates out, with both totals visible instead of hidden behind a menu.
 */
export const DocumentsStatusFilter = ({ value, onChange, counts }: DocumentsStatusFilterProps) => {
  const { t } = useTranslation("documents");

  return (
    <ToggleGroup
      type="single"
      value={value}
      // Radix clears a single-select group when the active item is clicked
      // again; a list must always be showing one of the two states.
      onValueChange={(next) => next && onChange(next as DocumentStatus)}
      variant="outline"
      aria-label={t("status.label")}
      className="h-9 shrink-0 justify-start"
    >
      {DOCUMENT_STATUSES.map((status) => {
        const Icon = STATUS_ICONS[status];
        const count = counts?.[status];
        return (
          <ToggleGroupItem
            key={status}
            value={status}
            // Below `sm` the label drops and the icon carries the meaning — the
            // states plus their totals share the row with the filter, view, and
            // overflow controls.
            aria-label={t(`status.${status}` as const)}
            className="h-9 shrink-0 gap-1.5 px-2.5 sm:gap-2 sm:px-3"
          >
            <Icon className="h-4 w-4" />
            <span className="hidden sm:inline">{t(`status.${status}` as const)}</span>
            {typeof count === "number" ? (
              <span className="text-muted-foreground text-xs tabular-nums">{count}</span>
            ) : null}
          </ToggleGroupItem>
        );
      })}
    </ToggleGroup>
  );
};
