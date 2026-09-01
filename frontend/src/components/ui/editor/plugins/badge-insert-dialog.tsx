import type { LexicalEditor } from "lexical";
import { $insertNodes } from "lexical";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { BadgeKind, SearchSuggestion } from "@/api/generated/initiativeAPI.schemas";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { $createBadgeNode } from "@/components/ui/editor/nodes/badge-node";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuildSearchSuggest } from "@/hooks/useSearch";
import { badgeEntityType } from "@/lib/badges";
import { hitIcon } from "@/lib/searchResults";

/** How many things the badge picker offers. */
const LIMIT = 8;

interface BadgeInsertDialogProps {
  badgeKind: BadgeKind;
  initiativeId: number | null;
  activeEditor: LexicalEditor;
  onClose: () => void;
}

/**
 * Choosing what a badge is about.
 *
 * The same lookup every picker in the app goes through, narrowed to the one
 * kind this badge can be about — a status badge asks for tasks and nothing
 * else, because the kind is half of what a badge is.
 */
export function BadgeInsertDialog({
  badgeKind,
  initiativeId,
  activeEditor,
  onClose,
}: BadgeInsertDialogProps) {
  const { t } = useTranslation(["documents", "common"]);
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 200);

  const { data } = useGuildSearchSuggest(debounced, {
    types: [badgeEntityType(badgeKind)],
    initiative_id: initiativeId ?? undefined,
    template: false,
    limit: LIMIT,
    enabled: (initiativeId ?? 0) > 0,
  });

  const insert = (suggestion: SearchSuggestion) => {
    activeEditor.update(() => {
      // The title is stored as the fallback: what an export shows, and what
      // stands in if the thing is later out of reach.
      $insertNodes([$createBadgeNode(badgeKind, suggestion.entity_id, suggestion.title)]);
    });
    onClose();
  };

  return (
    <div className="space-y-2">
      <Input
        autoFocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("badges.searchPlaceholder")}
        aria-label={t("badges.searchPlaceholder")}
      />
      <Command shouldFilter={false}>
        <CommandList>
          <CommandGroup>
            {(data ?? []).map((suggestion) => {
              const Icon = hitIcon(suggestion);
              return (
                <CommandItem
                  key={suggestion.entity_id}
                  value={String(suggestion.entity_id)}
                  onSelect={() => insert(suggestion)}
                  className="flex items-center gap-2"
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{suggestion.title}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  );
}
