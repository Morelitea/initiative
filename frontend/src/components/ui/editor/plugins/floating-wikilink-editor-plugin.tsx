import { Dispatch, JSX, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { mergeRegister } from "@lexical/utils";
import {
  $getNodeByKey,
  $getSelection,
  $isRangeSelection,
  $createTextNode,
  COMMAND_PRIORITY_HIGH,
  COMMAND_PRIORITY_LOW,
  KEY_ESCAPE_COMMAND,
  LexicalEditor,
  SELECTION_CHANGE_COMMAND,
} from "lexical";
import { ExternalLink, FileText, Link2Off, Plus, RefreshCw, Trash2 } from "lucide-react";
import { createPortal } from "react-dom";

import {
  $createWikilinkNode,
  $isWikilinkNode,
  WikilinkNode,
} from "@/components/ui/editor/nodes/wikilink-node";
import { getSelectedNode } from "@/components/ui/editor/utils/get-selected-node";
import { setFloatingElemPositionForLinkEditor } from "@/components/ui/editor/utils/set-floating-elem-position-for-link-editor";
import { Button } from "@/components/ui/button";
import { Command, CommandGroup, CommandItem, CommandList } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { autocompleteDocuments, type DocumentAutocomplete } from "@/lib/documentUtils";

interface FloatingWikilinkEditorProps {
  editor: LexicalEditor;
  wikilinkNode: WikilinkNode | null;
  wikilinkNodeKey: string | null;
  anchorElem: HTMLElement;
  initiativeId: number | null;
  onNavigate?: (documentId: number) => void;
  onCreateDocument?: (title: string, onCreated: (documentId: number) => void) => void;
  setWikilinkNode: Dispatch<WikilinkNode | null>;
}

function FloatingWikilinkEditor({
  editor,
  wikilinkNode,
  wikilinkNodeKey,
  anchorElem,
  initiativeId,
  onNavigate,
  onCreateDocument,
  setWikilinkNode,
}: FloatingWikilinkEditorProps): JSX.Element {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<DocumentAutocomplete[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const documentTitle = wikilinkNode?.getDocumentTitle() ?? "";
  const documentId = wikilinkNode?.getDocumentId() ?? null;
  const isResolved = wikilinkNode?.isResolved() ?? false;

  // Update editor position when wikilink changes
  const updatePosition = useCallback(() => {
    const editorElem = editorRef.current;
    if (!editorElem || !wikilinkNodeKey) {
      return;
    }

    const nativeSelection = window.getSelection();
    const rootElement = editor.getRootElement();

    if (
      wikilinkNode !== null &&
      nativeSelection !== null &&
      rootElement !== null &&
      rootElement.contains(nativeSelection.anchorNode) &&
      editor.isEditable()
    ) {
      const domRect: DOMRect | undefined =
        nativeSelection.focusNode?.parentElement?.getBoundingClientRect();
      if (domRect) {
        const adjustedRect = new DOMRect(domRect.x, domRect.y + 40, domRect.width, domRect.height);
        setFloatingElemPositionForLinkEditor(adjustedRect, editorElem, anchorElem);
      }
    } else {
      setFloatingElemPositionForLinkEditor(null, editorElem, anchorElem);
    }
  }, [anchorElem, editor, wikilinkNode, wikilinkNodeKey]);

  // Update position on changes
  useEffect(() => {
    updatePosition();
  }, [updatePosition, wikilinkNode]);

  // Listen for scroll and resize
  useEffect(() => {
    const scrollerElem = anchorElem.parentElement;

    const update = () => {
      editor.getEditorState().read(() => {
        updatePosition();
      });
    };

    window.addEventListener("resize", update);
    if (scrollerElem) {
      scrollerElem.addEventListener("scroll", update);
    }

    return () => {
      window.removeEventListener("resize", update);
      if (scrollerElem) {
        scrollerElem.removeEventListener("scroll", update);
      }
    };
  }, [anchorElem.parentElement, editor, updatePosition]);

  // Register escape key handler
  useEffect(() => {
    return editor.registerCommand(
      KEY_ESCAPE_COMMAND,
      () => {
        if (wikilinkNode !== null) {
          setWikilinkNode(null);
          setIsEditing(false);
          return true;
        }
        return false;
      },
      COMMAND_PRIORITY_HIGH
    );
  }, [editor, wikilinkNode, setWikilinkNode]);

  // Focus input when editing starts
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      setSearchQuery(documentTitle);
    }
  }, [isEditing, documentTitle]);

  // Search for documents
  useEffect(() => {
    if (!isEditing || !searchQuery || initiativeId === null) {
      setSearchResults([]);
      return;
    }

    let cancelled = false;
    const search = async () => {
      setIsSearching(true);
      try {
        const results = await autocompleteDocuments(initiativeId, searchQuery, 5);
        if (!cancelled) {
          setSearchResults(results);
        }
      } catch (error) {
        console.error("Failed to search documents:", error);
        if (!cancelled) {
          setSearchResults([]);
        }
      } finally {
        if (!cancelled) {
          setIsSearching(false);
        }
      }
    };

    const timeoutId = setTimeout(search, 150);
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [searchQuery, isEditing, initiativeId]);

  // Handle selecting a new document
  const handleSelectDocument = useCallback(
    (doc: DocumentAutocomplete) => {
      if (!wikilinkNodeKey) return;

      editor.update(() => {
        const node = $getNodeByKey(wikilinkNodeKey);
        if ($isWikilinkNode(node)) {
          const newWikilink = $createWikilinkNode(doc.title, doc.id);
          node.replace(newWikilink);
          newWikilink.select();
        }
      });

      setIsEditing(false);
      setWikilinkNode(null);
    },
    [editor, wikilinkNodeKey, setWikilinkNode]
  );

  // Handle creating a new document
  const handleCreateDocument = useCallback(() => {
    const title = searchQuery.trim() || documentTitle;
    if (title && onCreateDocument && wikilinkNodeKey) {
      // Pass a callback that updates the wikilink with the new document ID
      const nodeKey = wikilinkNodeKey;
      onCreateDocument(title, (newDocumentId: number) => {
        editor.update(() => {
          const node = $getNodeByKey(nodeKey);
          if ($isWikilinkNode(node)) {
            const newWikilink = $createWikilinkNode(node.getDocumentTitle(), newDocumentId);
            node.replace(newWikilink);
          }
        });
      });
    }
    setIsEditing(false);
    setWikilinkNode(null);
  }, [searchQuery, documentTitle, onCreateDocument, wikilinkNodeKey, editor, setWikilinkNode]);

  // Handle unlink (convert to plain text)
  const handleUnlink = useCallback(() => {
    if (!wikilinkNodeKey) return;

    editor.update(() => {
      const node = $getNodeByKey(wikilinkNodeKey);
      if ($isWikilinkNode(node)) {
        const textNode = $createTextNode(node.getTextContent());
        node.replace(textNode);
        textNode.select();
      }
    });

    setWikilinkNode(null);
  }, [editor, wikilinkNodeKey, setWikilinkNode]);

  // Handle delete
  const handleDelete = useCallback(() => {
    if (!wikilinkNodeKey) return;

    editor.update(() => {
      const node = $getNodeByKey(wikilinkNodeKey);
      if ($isWikilinkNode(node)) {
        node.remove();
      }
    });

    setWikilinkNode(null);
  }, [editor, wikilinkNodeKey, setWikilinkNode]);

  // Handle navigate
  const handleNavigate = useCallback(() => {
    if (documentId && onNavigate) {
      onNavigate(documentId);
    }
  }, [documentId, onNavigate]);

  // Check if search query has an exact match in results
  const hasExactMatch = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return searchResults.some((doc) => doc.title.toLowerCase() === normalizedQuery);
  }, [searchQuery, searchResults]);

  if (!wikilinkNode) {
    return (
      <div
        ref={editorRef}
        className="absolute top-0 left-0 w-full max-w-sm rounded-md opacity-0 shadow-md"
      />
    );
  }

  return (
    <div
      ref={editorRef}
      className="absolute top-0 left-0 z-50 w-full max-w-sm rounded-md opacity-0 shadow-md"
    >
      {isEditing ? (
        <div className="bg-card rounded-md border p-2 shadow-lg">
          <Input
            ref={inputRef}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search documents..."
            className="mb-2"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setIsEditing(false);
              }
            }}
          />
          {isSearching ? (
            <div className="text-muted-foreground p-2 text-sm">Searching...</div>
          ) : (
            <Command className="border-none shadow-none">
              <CommandList>
                <CommandGroup>
                  {searchResults.map((doc) => (
                    <CommandItem
                      key={doc.id}
                      value={doc.title}
                      onSelect={() => handleSelectDocument(doc)}
                      className="flex cursor-pointer items-center gap-2"
                    >
                      <FileText className="text-muted-foreground h-4 w-4" />
                      <span className="truncate">{doc.title}</span>
                    </CommandItem>
                  ))}
                  {searchQuery.trim() && !hasExactMatch && onCreateDocument && (
                    <CommandItem
                      value={`create-${searchQuery}`}
                      onSelect={handleCreateDocument}
                      className="flex cursor-pointer items-center gap-2"
                    >
                      <Plus className="text-muted-foreground h-4 w-4" />
                      <span className="truncate">Create &ldquo;{searchQuery.trim()}&rdquo;</span>
                    </CommandItem>
                  )}
                </CommandGroup>
              </CommandList>
            </Command>
          )}
          <div className="mt-2 flex justify-end">
            <Button variant="ghost" size="sm" onClick={() => setIsEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="bg-card flex items-center justify-between gap-2 rounded-md border p-2 shadow-lg">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="text-muted-foreground h-4 w-4 shrink-0" />
            <span
              className={`truncate text-sm ${!isResolved ? "text-muted-foreground italic" : ""}`}
            >
              {documentTitle}
              {!isResolved && " (unresolved)"}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {isResolved && onNavigate && (
              <Button
                size="icon"
                variant="ghost"
                onClick={handleNavigate}
                title="Open document"
                className="h-8 w-8"
              >
                <ExternalLink className="h-4 w-4" />
              </Button>
            )}
            {!isResolved && onCreateDocument && (
              <Button
                size="icon"
                variant="ghost"
                onClick={handleCreateDocument}
                title="Create document"
                className="h-8 w-8"
              >
                <Plus className="h-4 w-4" />
              </Button>
            )}
            <Button
              size="icon"
              variant="ghost"
              onClick={() => setIsEditing(true)}
              title="Change document"
              className="h-8 w-8"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              onClick={handleUnlink}
              title="Convert to plain text"
              className="h-8 w-8"
            >
              <Link2Off className="h-4 w-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              onClick={handleDelete}
              title="Delete"
              className="text-destructive hover:text-destructive h-8 w-8"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function useFloatingWikilinkEditor(
  editor: LexicalEditor,
  anchorElem: HTMLDivElement | null,
  initiativeId: number | null,
  onNavigate?: (documentId: number) => void,
  onCreateDocument?: (title: string, onCreated: (documentId: number) => void) => void
): JSX.Element | null {
  const [activeEditor, setActiveEditor] = useState(editor);
  const [wikilinkNode, setWikilinkNode] = useState<WikilinkNode | null>(null);
  const [wikilinkNodeKey, setWikilinkNodeKey] = useState<string | null>(null);

  useEffect(() => {
    function $updateWikilinkEditor() {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) {
        const node = getSelectedNode(selection);
        if ($isWikilinkNode(node)) {
          setWikilinkNode(node);
          setWikilinkNodeKey(node.getKey());
          return;
        }
      }
      setWikilinkNode(null);
      setWikilinkNodeKey(null);
    }

    return mergeRegister(
      editor.registerUpdateListener(({ editorState }) => {
        editorState.read(() => {
          $updateWikilinkEditor();
        });
      }),
      editor.registerCommand(
        SELECTION_CHANGE_COMMAND,
        (_payload, newEditor) => {
          $updateWikilinkEditor();
          setActiveEditor(newEditor);
          return false;
        },
        COMMAND_PRIORITY_LOW
      )
    );
  }, [editor]);

  if (!anchorElem) {
    return null;
  }

  return createPortal(
    <FloatingWikilinkEditor
      editor={activeEditor}
      wikilinkNode={wikilinkNode}
      wikilinkNodeKey={wikilinkNodeKey}
      anchorElem={anchorElem}
      initiativeId={initiativeId}
      onNavigate={onNavigate}
      onCreateDocument={onCreateDocument}
      setWikilinkNode={setWikilinkNode}
    />,
    anchorElem
  );
}

export interface FloatingWikilinkEditorPluginProps {
  anchorElem: HTMLDivElement | null;
  initiativeId: number | null;
  onNavigate?: (documentId: number) => void;
  onCreateDocument?: (title: string, onCreated: (documentId: number) => void) => void;
}

export function FloatingWikilinkEditorPlugin({
  anchorElem,
  initiativeId,
  onNavigate,
  onCreateDocument,
}: FloatingWikilinkEditorPluginProps): JSX.Element | null {
  const [editor] = useLexicalComposerContext();

  return useFloatingWikilinkEditor(editor, anchorElem, initiativeId, onNavigate, onCreateDocument);
}
