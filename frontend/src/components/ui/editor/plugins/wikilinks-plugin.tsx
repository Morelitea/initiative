import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  LexicalTypeaheadMenuPlugin,
  MenuOption,
  type MenuTextMatch,
} from "@lexical/react/LexicalTypeaheadMenuPlugin";
import {
  $getSelection,
  $isRangeSelection,
  $isTextNode,
  type LexicalEditor,
  type TextNode,
} from "lexical";
import { FileText, Plus } from "lucide-react";
import { type JSX, useCallback, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { $createEntityMentionNode } from "@/components/ui/editor/nodes/entity-mention-node";
import { useInitiative } from "@/hooks/useInitiatives";
import { useGuildSearchSuggest } from "@/hooks/useSearch";
import { linkableToolTypes } from "@/lib/references";

// Regex to match [[ followed by any characters (for partial wikilinks)
const WIKILINK_TRIGGER_REGEX = /(?:^|\s)\[\[([^\]]{0,75})$/;

// Regex to match complete wikilinks [[...]]
const COMPLETE_WIKILINK_REGEX = /\[\[([^\]]{1,75})\]\]/;

// Store trailing text to clean up after selection (text after cursor including ]])
let pendingTrailingCleanup: string | null = null;

function checkForWikilinkTrigger(text: string, editor: LexicalEditor): MenuTextMatch | null {
  const match = WIKILINK_TRIGGER_REGEX.exec(text);
  if (match !== null) {
    let matchingString = match[1];
    const replaceableString = match[0].trim();
    const leadOffset = match.index + (match[0].startsWith(" ") ? 1 : 0);

    // Reset trailing cleanup
    pendingTrailingCleanup = null;

    // Check if we're inside a complete wikilink by looking at full text around cursor
    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;

      const anchorNode = selection.anchor.getNode();
      if (!$isTextNode(anchorNode)) return;

      const fullText = anchorNode.getTextContent();
      const cursorOffset = selection.anchor.offset;

      // Find the [[ before cursor and ]] after cursor
      const textBeforeCursor = fullText.slice(0, cursorOffset);
      const textAfterCursor = fullText.slice(cursorOffset);

      // Check if there's an opening [[ before cursor (we already know there is from the regex)
      const openBracketIndex = textBeforeCursor.lastIndexOf("[[");
      if (openBracketIndex === -1) return;

      // Check if there's a closing ]] after cursor
      const closeBracketIndex = textAfterCursor.indexOf("]]");
      if (closeBracketIndex === -1) return;

      // Extract the full title between [[ and ]]
      const fullWikilink = fullText.slice(openBracketIndex, cursorOffset + closeBracketIndex + 2);
      const fullMatch = COMPLETE_WIKILINK_REGEX.exec(fullWikilink);
      if (fullMatch) {
        matchingString = fullMatch[1];
        // Store the text after cursor up to and including ]] for cleanup
        pendingTrailingCleanup = textAfterCursor.slice(0, closeBracketIndex + 2);
      }
    });

    return {
      leadOffset,
      matchingString,
      replaceableString,
    };
  }
  return null;
}

class WikilinkTypeaheadOption extends MenuOption {
  title: string;
  documentId: number | null;
  isCreateNew: boolean;
  /** What kind of thing this names. A row still to be created is a document:
   *  it is the one tool a name and an initiative are enough to make. */
  entityType: SearchEntityType;

  constructor(
    title: string,
    documentId: number | null,
    isCreateNew = false,
    entityType: SearchEntityType = SearchEntityType.document
  ) {
    super(`${entityType}-${documentId ?? "new"}-${title}`);
    this.title = title;
    this.documentId = documentId;
    this.isCreateNew = isCreateNew;
    this.entityType = entityType;
  }
}

const SUGGESTION_LIST_LENGTH_LIMIT = 10;

function useWikilinkSearch(
  queryString: string | null,
  initiativeId: number | null
): { options: WikilinkTypeaheadOption[]; isLoading: boolean } {
  // The shared lookup, narrowed to this initiative's live documents. A
  // wikilink points at a document to read, not at a blueprint.
  // `[[ ]]` reaches the TOOLS THIS INITIATIVE HAS — derived, so a seventh is
  // linkable the day it exists and one switched off is not offered at all.
  // Everything smaller than a tool (a task, an event) is reached with `#`:
  // those cannot be made from a name alone, which is the whole difference
  // between the two triggers.
  const { data: initiative } = useInitiative(initiativeId);
  const linkable = useMemo(() => linkableToolTypes(initiative), [initiative]);
  const { data, isFetching } = useGuildSearchSuggest(queryString ?? "", {
    types: linkable,
    initiative_id: initiativeId ?? undefined,
    template: false,
    limit: SUGGESTION_LIST_LENGTH_LIMIT,
    enabled: Boolean(queryString) && initiativeId !== null,
  });
  const results = useMemo(() => data ?? [], [data]);
  const isLoading = isFetching;

  const options = useMemo(() => {
    const docOptions = results.map(
      (hit) => new WikilinkTypeaheadOption(hit.title, hit.entity_id, false, hit.entity_type)
    );

    // Add "Create new document" option if query doesn't exactly match any result
    if (queryString && queryString.trim().length > 0) {
      const normalizedQuery = queryString.trim().toLowerCase();
      const exactMatch = results.some((doc) => doc.title.toLowerCase() === normalizedQuery);
      if (!exactMatch) {
        docOptions.push(new WikilinkTypeaheadOption(queryString.trim(), null, true));
      }
    }

    return docOptions;
  }, [results, queryString]);

  return { options, isLoading };
}

export interface WikilinksPluginProps {
  initiativeId: number | null;
  onNavigate?: (documentId: number) => void;
  /** Asked to make what `[[ ]]` could not find. The caller opens the dialog
   *  that knows which tools this initiative has; it answers with the reference
   *  to drop in. */
  onCreateThing?: (
    name: string,
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void
  ) => void;
}

export function WikilinksPlugin({
  initiativeId,
  onNavigate,
  onCreateThing,
}: WikilinksPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();
  const [queryString, setQueryString] = useState<string | null>(null);

  const { options, isLoading } = useWikilinkSearch(queryString, initiativeId);

  const onSelectOption = useCallback(
    (
      selectedOption: WikilinkTypeaheadOption,
      nodeToReplace: TextNode | null,
      closeMenu: () => void
    ) => {
      // Capture the trailing text to clean up before the editor update
      const trailingToCleanup = pendingTrailingCleanup;
      pendingTrailingCleanup = null;

      // Nothing matched, and `[[ ]]` is the trigger that can make one. The
      // dialog owns which kind and whether this writer may; the reference
      // comes back here to go in the sentence.
      if (selectedOption.isCreateNew) {
        closeMenu();
        onCreateThing?.(selectedOption.title, (entityType, entityId, name) => {
          editor.update(() => {
            const made = $createEntityMentionNode(entityType, entityId, name);
            if (nodeToReplace) nodeToReplace.replace(made);
            made.selectNext();
          });
        });
        return;
      }

      editor.update(() => {
        const wikilinkNode = $createEntityMentionNode(
          selectedOption.entityType,
          selectedOption.documentId ?? 0,
          selectedOption.title
        );
        if (nodeToReplace) {
          nodeToReplace.replace(wikilinkNode);
        }

        // Clean up trailing text (e.g., " world]]" when cursor was in middle of [[hello world]])
        if (trailingToCleanup) {
          const nextSibling = wikilinkNode.getNextSibling();
          if ($isTextNode(nextSibling)) {
            const siblingText = nextSibling.getTextContent();
            if (siblingText.startsWith(trailingToCleanup)) {
              const remainingText = siblingText.slice(trailingToCleanup.length);
              if (remainingText) {
                nextSibling.setTextContent(remainingText);
              } else {
                nextSibling.remove();
              }
            }
          }
        }

        wikilinkNode.selectNext();
        closeMenu();
      });
    },
    [editor, onCreateThing]
  );

  const checkForTriggerMatch = useCallback(
    (text: string) => {
      return checkForWikilinkTrigger(text, editor);
    },
    [editor]
  );

  if (initiativeId === null) {
    return null;
  }

  return (
    <LexicalTypeaheadMenuPlugin<WikilinkTypeaheadOption>
      onQueryChange={setQueryString}
      onSelectOption={onSelectOption}
      triggerFn={checkForTriggerMatch}
      options={options}
      anchorClassName="z-[60]"
      menuRenderFn={(
        anchorElementRef,
        { selectedIndex, selectOptionAndCleanUp, setHighlightedIndex }
      ) => {
        if (!anchorElementRef.current) {
          return null;
        }

        // Don't show menu if no query yet
        if (queryString === null) {
          return null;
        }

        // Show loading or options
        if (isLoading && options.length === 0) {
          return createPortal(
            <div className="absolute z-10 w-[300px] rounded-md border bg-popover p-2 text-popover-foreground shadow-md">
              <span className="text-muted-foreground text-sm">Searching...</span>
            </div>,
            anchorElementRef.current
          );
        }

        if (options.length === 0) {
          return createPortal(
            <div className="absolute z-10 w-[300px] rounded-md border bg-popover p-2 text-popover-foreground shadow-md">
              <span className="text-muted-foreground text-sm">
                Type to search, or make what is not there yet
              </span>
            </div>,
            anchorElementRef.current
          );
        }

        return createPortal(
          <div className="absolute z-10 w-[300px] rounded-md shadow-md">
            <Command
              onKeyDown={(e) => {
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setHighlightedIndex(
                    selectedIndex !== null
                      ? (selectedIndex - 1 + options.length) % options.length
                      : options.length - 1
                  );
                } else if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setHighlightedIndex(
                    selectedIndex !== null ? (selectedIndex + 1) % options.length : 0
                  );
                }
              }}
            >
              <CommandList>
                <CommandGroup>
                  {options.map((option, index) => (
                    <CommandItem
                      key={option.key}
                      value={option.title}
                      onSelect={() => {
                        selectOptionAndCleanUp(option);
                      }}
                      className={`flex items-center gap-2 ${
                        selectedIndex === index ? "bg-accent" : "bg-transparent!"
                      }`}
                    >
                      {option.isCreateNew ? (
                        <>
                          <Plus className="h-4 w-4 text-muted-foreground" />
                          <span className="truncate">Create &ldquo;{option.title}&rdquo;</span>
                        </>
                      ) : (
                        <>
                          <FileText className="h-4 w-4 text-muted-foreground" />
                          <span className="truncate">{option.title}</span>
                        </>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </div>,
          anchorElementRef.current
        );
      }}
    />
  );
}
