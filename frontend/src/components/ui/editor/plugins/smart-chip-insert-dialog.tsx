import type { LexicalEditor } from "lexical";
import { $insertNodes } from "lexical";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  SearchEntityType,
  SearchSuggestion,
  SmartChipKind,
} from "@/api/generated/initiativeAPI.schemas";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { $createSmartChipNode } from "@/components/ui/editor/nodes/smart-chip-node";
import { SMART_CHIP_MENU } from "@/components/ui/editor/plugins/smart-chip-menu";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuildRecentSuggestions, useGuildSearchSuggest } from "@/hooks/useSearch";
import { hitIcon } from "@/lib/searchResults";
import { CHIP_ENTITY_TYPES, chipEntityType, chipKindsFor } from "@/lib/smartChips";
import { cn } from "@/lib/utils";

/** How many things the chip picker offers. */
const LIMIT = 8;

interface SmartChipInsertDialogProps {
  /** The fact to show, where the caller already chose one — the `/` menu has
   *  an entry per fact. `null` asks for the thing first and the fact after. */
  chipKind?: SmartChipKind | null;
  initiativeId: number | null;
  activeEditor: LexicalEditor;
  onClose: () => void;
}

/**
 * Choosing what a chip is about.
 *
 * The same lookup every picker in the app goes through, narrowed to what a chip
 * can be about. Entered from `/task status` the kind is already settled, so
 * this asks only which task; entered from the toolbar it asks for the thing
 * first and then which of its facts to show — and skips that second step for a
 * thing with only one, because there is nothing to choose.
 */
export function SmartChipInsertDialog({
  chipKind = null,
  initiativeId,
  activeEditor,
  onClose,
}: SmartChipInsertDialogProps) {
  const { t } = useTranslation(["documents", "search"]);
  const searchRef = useRef<HTMLInputElement>(null);
  const factsRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 200);
  const [chosen, setChosen] = useState<SearchSuggestion | null>(null);

  // `autoFocus` alone loses this race. Whatever opened the dialog hands focus
  // back as it goes — the toolbar's select restores its trigger, the `/` menu
  // returns to the editor — and that happens after the dialog has mounted, so
  // the caret lands anywhere but here. Taking it on the next frame is after
  // both, which is the whole trick.
  useEffect(() => {
    const frame = requestAnimationFrame(() => (searchRef.current ?? factsRef.current)?.focus());
    return () => cancelAnimationFrame(frame);
  }, [chosen]);

  const types: SearchEntityType[] = chipKind ? [chipEntityType(chipKind)] : CHIP_ENTITY_TYPES;
  // A chip points at work inside this document's own initiative, so a document
  // that belongs to none has nothing to offer and should say so.
  const hasInitiative = (initiativeId ?? 0) > 0;

  const searched = debounced.trim().length > 0;
  const narrowing = {
    types,
    initiative_id: initiativeId ?? undefined,
    template: false,
    limit: LIMIT,
  };

  // Two questions, and a picker asks whichever one it is being used for. Before
  // anything is typed it is "what could I point at", which the lookup cannot
  // answer — it matches words, and there are none yet.
  const suggestions = useGuildRecentSuggestions({
    ...narrowing,
    enabled: hasInitiative && !searched,
  });
  const matches = useGuildSearchSuggest(debounced, {
    ...narrowing,
    enabled: hasInitiative && searched,
  });

  const active = searched ? matches : suggestions;
  // What came back is the previous query's answer, held so the list does not
  // empty between keystrokes. It is not an answer to what is typed NOW, so it
  // is shown but cannot be chosen.
  const stale = searched && matches.isPlaceholderData;
  const shown = active.data ?? [];

  const insert = (kind: SmartChipKind, suggestion: SearchSuggestion) => {
    activeEditor.update(() => {
      // The title is stored as the fallback: what an export shows, and what
      // stands in if the thing is later out of reach.
      $insertNodes([$createSmartChipNode(kind, suggestion.entity_id, suggestion.title)]);
    });
    onClose();
  };

  const choose = (suggestion: SearchSuggestion) => {
    if (chipKind) return insert(chipKind, suggestion);
    const kinds = chipKindsFor(suggestion.entity_type);
    // One fact means no question to ask.
    if (kinds.length === 1) return insert(kinds[0], suggestion);
    setChosen(suggestion);
  };

  if (chosen) {
    const ChosenIcon = hitIcon(chosen);
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <ChosenIcon className="size-4 shrink-0" />
          <span className="truncate">{chosen.title}</span>
        </div>
        <p className="text-muted-foreground text-xs">{t("smartChips.whichFact")}</p>
        {/* Nothing to type here — two or three fixed choices — so the list
            itself takes focus, which is what lets the arrows and Enter reach
            it. Without that this step is mouse-only. */}
        <Command ref={factsRef} shouldFilter={false} tabIndex={-1} className="border outline-none">
          <CommandList>
            <CommandGroup>
              {chipKindsFor(chosen.entity_type).map((kind) => {
                const entry = SMART_CHIP_MENU[kind];
                return (
                  <CommandItem
                    key={kind}
                    value={kind}
                    onSelect={() => insert(kind, chosen)}
                    className="flex items-center gap-2"
                  >
                    {entry.icon}
                    <span>{t(entry.labelKey as never)}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </div>
    );
  }

  const emptyMessage = !hasInitiative
    ? t("smartChips.noInitiative")
    : active.isFetching
      ? t("smartChips.searching")
      : searched
        ? t("smartChips.noMatches", { query: debounced })
        : t("smartChips.nothingYet");
  // The initiative is only worth explaining where there is one; a document
  // outside every initiative has already been told the whole story.
  const showScopeHint = hasInitiative && searched && !active.isFetching;

  return (
    <div className="space-y-2">
      {/* The field lives INSIDE the Command, which is what makes the list
          navigable: cmdk moves the highlight and answers Enter only for the
          input it owns. A search box beside a Command looks identical and
          leaves every suggestion mouse-only. */}
      <Command shouldFilter={false} className="border">
        <CommandInput
          ref={searchRef}
          value={query}
          onValueChange={setQuery}
          placeholder={t("smartChips.searchPlaceholder")}
          aria-label={t("smartChips.searchPlaceholder")}
        />
        <CommandList>
          {shown.length ? (
            <CommandGroup heading={searched ? undefined : t("smartChips.recent")}>
              {shown.map((suggestion) => {
                const Icon = hitIcon(suggestion);
                return (
                  <CommandItem
                    key={`${suggestion.entity_type}:${suggestion.entity_id}`}
                    value={`${suggestion.entity_type}:${suggestion.entity_id}`}
                    onSelect={() => !stale && choose(suggestion)}
                    disabled={stale}
                    className={cn("flex items-center gap-2", stale && "opacity-50")}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="truncate">{suggestion.title}</span>
                    {!chipKind && (
                      <span className="ml-auto shrink-0 text-muted-foreground text-xs">
                        {t(`search:types.${suggestion.entity_type}` as never)}
                      </span>
                    )}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          ) : (
            // Every one of these used to render as an empty box, which reads as
            // a broken dialog rather than as an answer.
            <div className="space-y-1 px-3 py-6 text-center">
              <p className="text-muted-foreground text-sm">{emptyMessage}</p>
              {showScopeHint && (
                <p className="text-muted-foreground/80 text-xs">{t("smartChips.scopeHint")}</p>
              )}
            </div>
          )}
        </CommandList>
      </Command>
    </div>
  );
}
