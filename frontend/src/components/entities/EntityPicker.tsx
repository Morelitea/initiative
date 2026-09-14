import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type EndpointRef,
  SearchEntityType,
  type SearchSuggestion,
} from "@/api/generated/initiativeAPI.schemas";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { useGuildPickerSuggestions } from "@/hooks/useSearch";
import { hitIcon } from "@/lib/searchResults";

/**
 * The kinds a relation picker offers, derived from the generated enum so a kind
 * added server-side is offered here without an edit.
 *
 * Two are left out. A **comment** is not referenceable at all, so no edge may
 * name one. A **tag** may sit on an edge — that is how tagging is stored — but
 * it is chosen with the tag picker, because a label is not something you pick a
 * relationship type for.
 */
export const LINKABLE_TYPES: SearchEntityType[] = Object.values(SearchEntityType).filter(
  (type) => type !== SearchEntityType.comment && type !== SearchEntityType.tag
);

interface EntityPickerProps {
  /**
   * The thing being linked from, so it is never offered as its own far end.
   * Absent while linking from something that does not exist yet — a queue item
   * being composed — where there is no self to leave out.
   */
  subject?: EndpointRef;
  /** Links made here stay inside one initiative, which the server enforces. */
  initiativeId: number | null;
  /** Narrow what may be picked. Defaults to every kind an edge may name. */
  types?: SearchEntityType[];
  value: SearchSuggestion | null;
  onChange: (value: SearchSuggestion | null) => void;
  disabled?: boolean;
}

/**
 * Pick one thing of any kind.
 *
 * The search that backs it is the same one every other picker in the app uses,
 * only without a kind narrowed down to one — so it offers what somebody looked
 * at recently before anything is typed, and matches by name once something is.
 * Each row says what kind of thing it is, because in a list drawn from thirteen
 * of them a name alone often is not enough to tell two apart.
 *
 * It hands back the whole suggestion rather than an id: the caller needs the
 * kind to build the edge, and the title to keep showing what is selected after
 * the query has moved on.
 */
export const EntityPicker = ({
  subject,
  initiativeId,
  types,
  value,
  onChange,
  disabled,
}: EntityPickerProps) => {
  const { t } = useTranslation(["relations", "search"]);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const suggestions = useGuildPickerSuggestions(query, {
    types: types ?? LINKABLE_TYPES,
    initiative_id: initiativeId ?? undefined,
    // A template's contents are not what somebody is reaching for here.
    template: false,
    subject: subject ? `${subject.type}:${subject.id}` : undefined,
    enabled: open,
  });

  const byValue = useMemo(() => {
    const map = new Map<string, SearchSuggestion>();
    for (const item of suggestions.items) {
      map.set(`${item.entity_type}:${item.entity_id}`, item);
    }
    return map;
  }, [suggestions.items]);

  const items = useMemo(
    () =>
      suggestions.items.map((item) => ({
        value: `${item.entity_type}:${item.entity_id}`,
        label: item.title,
        icon: hitIcon(item),
        hint: t(`search:types.${item.entity_type}`, { defaultValue: item.entity_type }),
      })),
    [suggestions.items, t]
  );

  return (
    <AsyncCombobox
      items={items}
      value={value ? `${value.entity_type}:${value.entity_id}` : null}
      selectedLabel={value?.title ?? null}
      onValueChange={(next) => onChange(byValue.get(next) ?? null)}
      onSearchChange={setQuery}
      onOpenChange={setOpen}
      loading={suggestions.isLoading}
      placeholder={t("relations:dialog.entityPlaceholder")}
      searchPlaceholder={t("relations:dialog.entityPlaceholder")}
      emptyMessage={t("relations:dialog.noResults")}
      aria-label={t("relations:dialog.entity")}
      disabled={disabled}
    />
  );
};
