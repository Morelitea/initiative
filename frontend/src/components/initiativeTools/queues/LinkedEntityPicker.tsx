import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Label } from "@/components/ui/label";

/**
 * A document or task linked to a queue item. ``title`` labels its chip; the
 * queue item's own links don't always carry one, so the chip falls back to the
 * id.
 */
export type LinkedEntity = {
  id: number;
  title?: string;
};

/** How many typeahead matches to request per keystroke-pause. */
export const ENTITY_PICKER_PAGE_SIZE = 20;

type LinkedEntityPickerProps = {
  label: string;
  /** Currently linked entities, rendered as removable chips. */
  selected: LinkedEntity[];
  onChange: (next: LinkedEntity[]) => void;
  /** Typeahead results for the live query. */
  results: LinkedEntity[];
  loading?: boolean;
  onSearchChange: (query: string) => void;
  onOpenChange: (open: boolean) => void;
  /** Route for an entity's chip link, e.g. ``(id) => gp(`/documents/${id}`)``. */
  hrefFor: (id: number) => string;
  placeholder: string;
  emptyMessage: string;
  /** Show the existing links as plain chips, with no way to add or remove. */
  readOnly?: boolean;
};

/**
 * Server-typeahead picker for the entities linked to a queue item, plus the
 * chips for what's already linked.
 */
export const LinkedEntityPicker = ({
  label,
  selected,
  onChange,
  results,
  loading,
  onSearchChange,
  onOpenChange,
  hrefFor,
  placeholder,
  emptyMessage,
  readOnly = false,
}: LinkedEntityPickerProps) => {
  const { t } = useTranslation("queues");

  const selectedIds = new Set(selected.map((entity) => entity.id));
  // Filtering the already-linked out of a small result page — the server has
  // no notion of this form's pending selections.
  const items = results
    .filter((entity) => !selectedIds.has(entity.id))
    .map((entity) => ({ value: String(entity.id), label: entity.title || `#${entity.id}` }));

  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      {!readOnly && (
        <AsyncCombobox
          items={items}
          value={null}
          onValueChange={(value) => {
            const picked = results.find((entity) => String(entity.id) === value);
            if (picked && !selectedIds.has(picked.id)) {
              onChange([...selected, picked]);
            }
          }}
          onSearchChange={onSearchChange}
          onOpenChange={onOpenChange}
          loading={loading}
          placeholder={placeholder}
          emptyMessage={emptyMessage}
        />
      )}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selected.map((entity) => (
            <span
              key={entity.id}
              className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs"
            >
              <Link
                to={hrefFor(entity.id)}
                className="hover:text-primary hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {entity.title || `#${entity.id}`}
              </Link>
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => onChange(selected.filter((e) => e.id !== entity.id))}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={t("removeLink")}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
