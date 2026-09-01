import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  LexicalTypeaheadMenuPlugin,
  MenuOption,
  type MenuTextMatch,
} from "@lexical/react/LexicalTypeaheadMenuPlugin";
import { useNavigate } from "@tanstack/react-router";
import { CLICK_COMMAND, COMMAND_PRIORITY_LOW, type TextNode } from "lexical";
import { type JSX, useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import type { SearchSuggestion } from "@/api/generated/initiativeAPI.schemas";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { $createEntityMentionNode } from "@/components/ui/editor/nodes/entity-mention-node";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuildSearchSuggest } from "@/hooks/useSearch";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";
import { activeMention, ENTITY_TRIGGER, MENTIONABLE_TYPES } from "@/lib/mentions";
import { hitIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";

/** How many things the `#` menu offers at once. */
const SUGGESTION_LIMIT = 5;

class EntityOption extends MenuOption {
  constructor(readonly suggestion: SearchSuggestion) {
    super(`${suggestion.entity_type}-${suggestion.entity_id}`);
  }
}

/**
 * The mention being typed at the caret, in the shape Lexical's typeahead wants.
 *
 * `activeMention` is the same reader the comment composer uses, so `#` behaves
 * identically in a document and in a comment — including narrowing with
 * `#task:` and the kinds that derive from the entity types.
 */
export function entityMatch(text: string): MenuTextMatch | null {
  const active = activeMention(text);
  if (!active || active.user) return null;
  const replaceable = text.slice(text.length - active.length);
  return {
    leadOffset: text.length - active.length,
    // Everything after the `#`, type word included, so the narrowing is not
    // lost on the way through Lexical — the menu reads it back below.
    matchingString: replaceable.slice(ENTITY_TRIGGER.length),
    replaceableString: replaceable,
  };
}

export interface EntityMentionsPluginProps {
  /** Initiative the document belongs to — what a mention may reach. */
  initiativeId?: number | null;
}

/**
 * `#` in a document, offering everything in its initiative.
 *
 * Mounted only for a standard document: a whiteboard and a spreadsheet are not
 * prose and have no caret to type a trigger into, and a file or a linked page
 * has no editable body at all.
 */
export function EntityMentionsPlugin({
  initiativeId,
}: EntityMentionsPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();
  const navigate = useNavigate();
  const guildId = useActiveGuildId();
  const [queryString, setQueryString] = useState<string | null>(null);
  // Read back through the same parser the comment composer uses, so `#task:`
  // narrows here exactly as it does there.
  const active = useMemo(
    () => (queryString === null ? null : activeMention(`${ENTITY_TRIGGER}${queryString}`)),
    [queryString]
  );
  const debouncedQuery = useDebouncedValue(active?.query ?? "", 200);

  // The one lookup every picker in the app goes through, narrowed to this
  // initiative's live work.
  const { data } = useGuildSearchSuggest(debouncedQuery, {
    types: active?.types ?? MENTIONABLE_TYPES,
    initiative_id: initiativeId ?? undefined,
    template: false,
    limit: SUGGESTION_LIMIT,
    enabled: active !== null && (initiativeId ?? 0) > 0,
  });

  const options = useMemo(() => (data ?? []).map((s) => new EntityOption(s)), [data]);

  const onSelectOption = useCallback(
    (option: EntityOption, nodeToReplace: TextNode | null, closeMenu: () => void) => {
      editor.update(() => {
        const node = $createEntityMentionNode(
          option.suggestion.entity_type,
          option.suggestion.entity_id,
          option.suggestion.title
        );
        if (nodeToReplace) nodeToReplace.replace(node);
        node.select();
        closeMenu();
      });
    },
    [editor]
  );

  // A mention names a thing; clicking it opens that thing. The address of an
  // entity includes its initiative, which a mention does not carry, so this
  // goes through the `/go` resolver like every other bare-id link.
  useEffect(() => {
    return editor.registerCommand(
      CLICK_COMMAND,
      (event: MouseEvent) => {
        const target = event.target as HTMLElement | null;
        const type = target?.getAttribute("data-lexical-entity-mention");
        const id = Number(target?.getAttribute("data-entity-id"));
        if (!type || !Number.isFinite(id)) return false;
        const refType = entityRefTypeFor(type as SearchSuggestion["entity_type"]);
        if (!refType) return false;
        event.preventDefault();
        void navigate({ to: guildPath(guildId, entityRefRoute(refType, id)) });
        return true;
      },
      COMMAND_PRIORITY_LOW
    );
  }, [editor, navigate, guildId]);

  if (!initiativeId) return null;

  return (
    <LexicalTypeaheadMenuPlugin<EntityOption>
      onQueryChange={setQueryString}
      onSelectOption={onSelectOption}
      triggerFn={entityMatch}
      options={options}
      menuRenderFn={(anchorElementRef, { selectedIndex, selectOptionAndCleanUp }) =>
        anchorElementRef.current && options.length
          ? createPortal(
              <div className="absolute z-10 w-[260px] rounded-md shadow-md">
                <Command>
                  <CommandList>
                    <CommandGroup>
                      {options.map((option, index) => {
                        const Icon = hitIcon(option.suggestion);
                        return (
                          <CommandItem
                            key={option.key}
                            value={option.key}
                            onSelect={() => selectOptionAndCleanUp(option)}
                            className={`flex items-center gap-2 ${
                              selectedIndex === index ? "bg-accent" : "bg-transparent!"
                            }`}
                          >
                            <Icon className="h-4 w-4 shrink-0" />
                            <span className="truncate">{option.suggestion.title}</span>
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </div>,
              anchorElementRef.current
            )
          : null
      }
    />
  );
}
