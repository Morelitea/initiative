import { JSX, lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { MenuOption, MenuTextMatch } from "@lexical/react/LexicalTypeaheadMenuPlugin";
import {
  $getNodeByKey,
  $getNearestNodeFromDOMNode,
  $getSelection,
  $isRangeSelection,
  $isTextNode,
  CLICK_COMMAND,
  COMMAND_PRIORITY_LOW,
  LexicalEditor,
  TextNode,
} from "lexical";
import { createPortal } from "react-dom";
import { FileText, Plus } from "lucide-react";

import { $createWikilinkNode, $isWikilinkNode } from "@/components/ui/editor/nodes/wikilink-node";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { autocompleteDocuments, type DocumentAutocomplete } from "@/api/documents";

const LexicalTypeaheadMenuPlugin = lazy(() =>
  import("@lexical/react/LexicalTypeaheadMenuPlugin").then((mod) => ({
    default: mod.LexicalTypeaheadMenuPlugin<WikilinkTypeaheadOption>,
  }))
);

// Regex to match [[ followed by any characters (for partial wikilinks)
const WIKILINK_TRIGGER_REGEX = /(?:^|\s)\[\[([^\]]{0,75})$/;

// Regex to match complete wikilinks [[...]]
const COMPLETE_WIKILINK_REGEX = /\[\[([^\]]{1,75})\]\]/;

function checkForWikilinkTrigger(text: string, editor: LexicalEditor): MenuTextMatch | null {
  const match = WIKILINK_TRIGGER_REGEX.exec(text);
  if (match !== null) {
    let matchingString = match[1];
    let replaceableString = match[0].trim();
    const leadOffset = match.index + (match[0].startsWith(" ") ? 1 : 0);

    // Check if we're inside a complete wikilink by looking at full text around cursor
    let fullWikilinkTitle: string | null = null;
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
        fullWikilinkTitle = fullMatch[1];
      }
    });

    // If we found a complete wikilink, use the full title
    if (fullWikilinkTitle !== null) {
      matchingString = fullWikilinkTitle;
      replaceableString = `[[${fullWikilinkTitle}]]`;
    }

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

  constructor(title: string, documentId: number | null, isCreateNew = false) {
    super(title);
    this.title = title;
    this.documentId = documentId;
    this.isCreateNew = isCreateNew;
  }
}

const SUGGESTION_LIST_LENGTH_LIMIT = 10;

function useWikilinkSearch(
  queryString: string | null,
  initiativeId: number | null
): { options: WikilinkTypeaheadOption[]; isLoading: boolean } {
  const [results, setResults] = useState<DocumentAutocomplete[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (queryString === null || queryString.length === 0 || initiativeId === null) {
      setResults([]);
      return;
    }

    let cancelled = false;
    const fetchDocuments = async () => {
      setIsLoading(true);
      try {
        const docs = await autocompleteDocuments(
          initiativeId,
          queryString,
          SUGGESTION_LIST_LENGTH_LIMIT
        );
        if (!cancelled) {
          setResults(docs);
        }
      } catch (error) {
        console.error("Failed to fetch documents for wikilink autocomplete:", error);
        if (!cancelled) {
          setResults([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    // Debounce the API call
    const timeoutId = setTimeout(fetchDocuments, 150);
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [queryString, initiativeId]);

  const options = useMemo(() => {
    const docOptions = results.map((doc) => new WikilinkTypeaheadOption(doc.title, doc.id, false));

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
  onCreateDocument?: (title: string, onCreated: (documentId: number) => void) => void;
}

export function WikilinksPlugin({
  initiativeId,
  onNavigate,
  onCreateDocument,
}: WikilinksPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();
  const [queryString, setQueryString] = useState<string | null>(null);

  const { options, isLoading } = useWikilinkSearch(queryString, initiativeId);

  // Register click handler for wikilinks
  useEffect(() => {
    return editor.registerCommand(
      CLICK_COMMAND,
      (event: MouseEvent) => {
        const target = event.target as HTMLElement;

        // Check if clicked element is a wikilink
        if (!target.hasAttribute("data-lexical-wikilink")) {
          return false;
        }

        event.preventDefault();
        event.stopPropagation();

        const documentIdAttr = target.getAttribute("data-document-id");

        if (documentIdAttr) {
          // Resolved wikilink - navigate
          const documentId = parseInt(documentIdAttr, 10);
          if (!isNaN(documentId)) {
            onNavigate?.(documentId);
          }
        } else {
          // Unresolved wikilink - offer to create document
          const title = target.textContent || "";
          if (title && onCreateDocument) {
            // Find the wikilink node to pass an update callback
            editor.getEditorState().read(() => {
              const node = $getNearestNodeFromDOMNode(target);
              if ($isWikilinkNode(node)) {
                const nodeKey = node.getKey();
                onCreateDocument(title, (newDocumentId: number) => {
                  editor.update(() => {
                    const wikilinkNode = $getNodeByKey(nodeKey);
                    if ($isWikilinkNode(wikilinkNode)) {
                      const updatedWikilink = $createWikilinkNode(
                        wikilinkNode.getDocumentTitle(),
                        newDocumentId
                      );
                      wikilinkNode.replace(updatedWikilink);
                    }
                  });
                });
              }
            });
          }
        }

        return true;
      },
      COMMAND_PRIORITY_LOW
    );
  }, [editor, onNavigate, onCreateDocument]);

  const onSelectOption = useCallback(
    (
      selectedOption: WikilinkTypeaheadOption,
      nodeToReplace: TextNode | null,
      closeMenu: () => void
    ) => {
      editor.update(() => {
        const wikilinkNode = $createWikilinkNode(selectedOption.title, selectedOption.documentId);
        if (nodeToReplace) {
          nodeToReplace.replace(wikilinkNode);
        }
        wikilinkNode.select();
        closeMenu();
      });
    },
    [editor]
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
    <Suspense fallback={null}>
      <LexicalTypeaheadMenuPlugin
        onQueryChange={setQueryString}
        onSelectOption={onSelectOption}
        triggerFn={checkForTriggerMatch}
        options={options}
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
              <div className="bg-popover text-popover-foreground absolute z-10 w-[300px] rounded-md border p-2 shadow-md">
                <span className="text-muted-foreground text-sm">Searching...</span>
              </div>,
              anchorElementRef.current
            );
          }

          if (options.length === 0) {
            return createPortal(
              <div className="bg-popover text-popover-foreground absolute z-10 w-[300px] rounded-md border p-2 shadow-md">
                <span className="text-muted-foreground text-sm">
                  Type to search or create a new document
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
                            <Plus className="text-muted-foreground h-4 w-4" />
                            <span className="truncate">Create &ldquo;{option.title}&rdquo;</span>
                          </>
                        ) : (
                          <>
                            <FileText className="text-muted-foreground h-4 w-4" />
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
    </Suspense>
  );
}
