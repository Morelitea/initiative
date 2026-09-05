import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { TabIndentationPlugin } from "@lexical/react/LexicalTabIndentationPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";
import { type RefObject, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { ContentEditable } from "@/components/ui/editor/editor-ui/content-editable";
import { MARKDOWN_TRANSFORMERS } from "@/components/ui/editor/extensions/markdown-shortcuts-extension";
import { ActionsPlugin } from "@/components/ui/editor/plugins/actions/actions-plugin";
import { CharacterLimitPlugin } from "@/components/ui/editor/plugins/actions/character-limit-plugin";
import { ClearEditorActionPlugin } from "@/components/ui/editor/plugins/actions/clear-editor-plugin";
import { CounterCharacterPlugin } from "@/components/ui/editor/plugins/actions/counter-character-plugin";
import { EditModeTogglePlugin } from "@/components/ui/editor/plugins/actions/edit-mode-toggle-plugin";
import { ImportExportPlugin } from "@/components/ui/editor/plugins/actions/import-export-plugin";
import { MarkdownTogglePlugin } from "@/components/ui/editor/plugins/actions/markdown-toggle-plugin";
import { SpeechToTextPlugin } from "@/components/ui/editor/plugins/actions/speech-to-text-plugin";
import { TreeViewPlugin } from "@/components/ui/editor/plugins/actions/tree-view-plugin";
import { CodeActionMenuPlugin } from "@/components/ui/editor/plugins/code-action-menu-plugin";
import { ComponentPickerMenuPlugin } from "@/components/ui/editor/plugins/component-picker-menu-plugin";
import { ContextMenuPlugin } from "@/components/ui/editor/plugins/context-menu-plugin";
import { DragDropPastePlugin } from "@/components/ui/editor/plugins/drag-drop-paste-plugin";
import { DraggableBlockPlugin } from "@/components/ui/editor/plugins/draggable-block-plugin";
import { AutoEmbedPlugin } from "@/components/ui/editor/plugins/embeds/auto-embed-plugin";
import { TwitterPlugin } from "@/components/ui/editor/plugins/embeds/twitter-plugin";
import { YouTubePlugin } from "@/components/ui/editor/plugins/embeds/youtube-plugin";
import { EmojiPickerPlugin } from "@/components/ui/editor/plugins/emoji-picker-plugin";
import { EntityMentionsPlugin } from "@/components/ui/editor/plugins/entity-mentions-plugin";
import { FloatingLinkEditorPlugin } from "@/components/ui/editor/plugins/floating-link-editor-plugin";
import { FloatingTextFormatToolbarPlugin } from "@/components/ui/editor/plugins/floating-text-format-plugin";
import { LegacyNodesPlugin } from "@/components/ui/editor/plugins/legacy-nodes-plugin";
import { LinkSanitizePlugin } from "@/components/ui/editor/plugins/link-sanitize-plugin";
import { MentionsPlugin } from "@/components/ui/editor/plugins/mentions-plugin";
import { AlignmentPickerPlugin } from "@/components/ui/editor/plugins/picker/alignment-picker-plugin";
import { BulletedListPickerPlugin } from "@/components/ui/editor/plugins/picker/bulleted-list-picker-plugin";
import { CheckListPickerPlugin } from "@/components/ui/editor/plugins/picker/check-list-picker-plugin";
import { CodePickerPlugin } from "@/components/ui/editor/plugins/picker/code-picker-plugin";
import { ColumnsLayoutPickerPlugin } from "@/components/ui/editor/plugins/picker/columns-layout-picker-plugin";
import { DividerPickerPlugin } from "@/components/ui/editor/plugins/picker/divider-picker-plugin";
import { EmbedsPickerPlugin } from "@/components/ui/editor/plugins/picker/embeds-picker-plugin";
import { HeadingPickerPlugin } from "@/components/ui/editor/plugins/picker/heading-picker-plugin";
import { ImagePickerPlugin } from "@/components/ui/editor/plugins/picker/image-picker-plugin";
import { NumberedListPickerPlugin } from "@/components/ui/editor/plugins/picker/numbered-list-picker-plugin";
import { ParagraphPickerPlugin } from "@/components/ui/editor/plugins/picker/paragraph-picker-plugin";
import { QuotePickerPlugin } from "@/components/ui/editor/plugins/picker/quote-picker-plugin";
import { SmartChipPickerPlugins } from "@/components/ui/editor/plugins/picker/smart-chip-picker-plugin";
import {
  DynamicTablePickerPlugin,
  TablePickerPlugin,
} from "@/components/ui/editor/plugins/picker/table-picker-plugin";
import { SmartChipRefsPlugin } from "@/components/ui/editor/plugins/smart-chip-refs-plugin";
import { TabFocusPlugin } from "@/components/ui/editor/plugins/tab-focus-plugin";
import { TableActionMenuPlugin } from "@/components/ui/editor/plugins/table-action-menu-plugin";
import { FormatBulletedList } from "@/components/ui/editor/plugins/toolbar/block-format/format-bulleted-list";
import { FormatCheckList } from "@/components/ui/editor/plugins/toolbar/block-format/format-check-list";
import { FormatCodeBlock } from "@/components/ui/editor/plugins/toolbar/block-format/format-code-block";
import { FormatHeading } from "@/components/ui/editor/plugins/toolbar/block-format/format-heading";
import { FormatNumberedList } from "@/components/ui/editor/plugins/toolbar/block-format/format-numbered-list";
import { FormatParagraph } from "@/components/ui/editor/plugins/toolbar/block-format/format-paragraph";
import { FormatQuote } from "@/components/ui/editor/plugins/toolbar/block-format/format-quote";
import { BlockFormatDropDown } from "@/components/ui/editor/plugins/toolbar/block-format-toolbar-plugin";
import { InsertColumnsLayout } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-columns-layout";
import { InsertEmbeds } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-embeds";
import { InsertHorizontalRule } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-horizontal-rule";
import { InsertImage } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-image";
import { InsertSmartChip } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-smart-chip";
import { InsertTable } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-table";
import { BlockInsertPlugin } from "@/components/ui/editor/plugins/toolbar/block-insert-plugin";
import { ClearFormattingToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/clear-formatting-toolbar-plugin";
import { CodeLanguageToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/code-language-toolbar-plugin";
import { ElementFormatToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/element-format-toolbar-plugin";
import { FontBackgroundToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-background-toolbar-plugin";
import { FontColorToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-color-toolbar-plugin";
import { FontFormatToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-format-toolbar-plugin";
import { FontSizeToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-size-toolbar-plugin";
import { HistoryToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/history-toolbar-plugin";
import { LinkToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/link-toolbar-plugin";
import { SubSuperToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/subsuper-toolbar-plugin";
import { ToolbarOverflowMenu } from "@/components/ui/editor/plugins/toolbar/toolbar-overflow-menu";
import { ToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/toolbar-plugin";
import { WikilinksPlugin } from "@/components/ui/editor/plugins/wikilinks-plugin";
import type { EditorVariant } from "@/components/ui/editor/variant";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const placeholder = "Press / for commands...";

export function Plugins({
  showToolbar = true,
  readOnly = false,
  collaborative = false,
  cursorsContainerRef,
  initiativeId = null,
  supportsEntityMentions = false,
  variant = "document",
  maxLength,
  compact = false,
  onWikilinkNavigate,
  onCreateReferencedThing,
}: {
  showToolbar?: boolean;
  readOnly?: boolean;
  collaborative?: boolean;
  cursorsContainerRef?: RefObject<HTMLDivElement>;
  initiativeId?: number | null;
  /** Whether this is a standard document — prose with a caret. `#` is offered
   *  only here: a whiteboard and a spreadsheet are not written into, and a file
   *  or a linked page has no body of its own to write in. */
  supportsEntityMentions?: boolean;
  /** Which surface this is. `post` narrows the toolbar to what writing a
   *  notice needs — see `EditorVariant`. */
  variant?: EditorVariant;
  /** Characters a body may hold, shown as a remaining count. The server is
   *  still the authority; this is so nobody writes past the limit unaware. */
  maxLength?: number;
  /** The container already supplies the horizontal gutter — a post rendered
   *  in a card on the board, say — so the editor takes none of its own.
   *
   *  Deliberately not derived from `readOnly`: a post's own page renders it
   *  read-only for anyone without write access, and there the body must sit at
   *  the same offset a writer sees, not shift left because of who is looking.
   *  Height is a separate question and does follow `readOnly`. */
  compact?: boolean;
  onWikilinkNavigate?: (documentId: number) => void;
  onCreateReferencedThing?: (
    name: string,
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void
  ) => void;
}) {
  const { t } = useTranslation("documents");
  const [editor] = useLexicalComposerContext();
  // The typesetting half of the toolbar. A document is a place to typeset; a
  // notice is a place to say something, so it gets the writing controls and
  // not the layout ones.
  const rich = variant === "document";
  const [floatingAnchorElem, setFloatingAnchorElem] = useState<HTMLDivElement | null>(null);
  const [isLinkEditMode, setIsLinkEditMode] = useState<boolean>(false);

  // Enforce read-only mode
  useEffect(() => {
    editor.setEditable(!readOnly);
  }, [editor, readOnly]);

  const onRef = (_floatingAnchorElem: HTMLDivElement) => {
    if (_floatingAnchorElem !== null) {
      setFloatingAnchorElem(_floatingAnchorElem);
    }
  };

  return (
    // A column that fills the editor's scrollport (which has a definite height
    // only in fullscreen; elsewhere `min-h-full` resolves to auto and this is a
    // plain block). The content region below grows into the leftover space so
    // the actions bar's `sticky bottom-0` has somewhere to stick to even when
    // the document is shorter than the viewport.
    <div className="relative flex min-h-full flex-col">
      {showToolbar && (
        <ToolbarPlugin>
          {({ blockType }) => (
            <>
              {/* Desktop toolbar - all options inline */}
              <div className="vertical-align-middle sticky top-0 z-10 hidden flex-wrap items-center gap-2 overflow-auto border-b bg-muted p-1 lg:flex">
                <HistoryToolbarPlugin />
                <Separator orientation="vertical" className="h-7!" />
                <BlockFormatDropDown>
                  <FormatParagraph />
                  <FormatHeading levels={["h1", "h2", "h3"]} />
                  <FormatNumberedList />
                  <FormatBulletedList />
                  <FormatCheckList />
                  <FormatCodeBlock />
                  <FormatQuote />
                </BlockFormatDropDown>
                {blockType === "code" ? (
                  <CodeLanguageToolbarPlugin />
                ) : (
                  <>
                    {rich && (
                      <>
                        <FontSizeToolbarPlugin />
                        <Separator orientation="vertical" className="h-7!" />
                      </>
                    )}
                    <FontFormatToolbarPlugin />
                    <Separator orientation="vertical" className="h-7!" />
                    {rich && <SubSuperToolbarPlugin />}
                    <LinkToolbarPlugin setIsLinkEditMode={setIsLinkEditMode} />
                    <Separator orientation="vertical" className="h-7!" />
                    {/* Alignment, clearing formatting and the colour pickers
                        are all one-in-a-hundred on a notice. On a post they
                        move into the overflow at the end of the row rather
                        than costing a second row of buttons above every
                        composer; on a document they stay where they were. */}
                    {rich && (
                      <>
                        <ClearFormattingToolbarPlugin />
                        <Separator orientation="vertical" className="h-7!" />
                        <FontColorToolbarPlugin />
                        <FontBackgroundToolbarPlugin />
                        <Separator orientation="vertical" className="h-7!" />
                        <ElementFormatToolbarPlugin />
                        <Separator orientation="vertical" className="h-7!" />
                      </>
                    )}
                    <BlockInsertPlugin>
                      {rich && <InsertHorizontalRule />}
                      <InsertImage />
                      <InsertTable />
                      {rich && <InsertColumnsLayout />}
                      <InsertEmbeds />
                      {supportsEntityMentions && <InsertSmartChip initiativeId={initiativeId} />}
                    </BlockInsertPlugin>
                    {!rich && (
                      <ToolbarOverflowMenu
                        initiativeId={initiativeId}
                        supportsSmartChips={supportsEntityMentions}
                        variant={variant}
                      />
                    )}
                  </>
                )}
              </div>

              {/* Compact toolbar - overflow menu */}
              <div className="vertical-align-middle sticky top-0 z-10 flex items-center gap-2 border-b bg-muted p-1 lg:hidden">
                <HistoryToolbarPlugin />
                <Separator orientation="vertical" className="h-7!" />
                <BlockFormatDropDown>
                  <FormatParagraph />
                  <FormatHeading levels={["h1", "h2", "h3"]} />
                  <FormatNumberedList />
                  <FormatBulletedList />
                  <FormatCheckList />
                  <FormatCodeBlock />
                  <FormatQuote />
                </BlockFormatDropDown>
                {blockType === "code" ? (
                  <CodeLanguageToolbarPlugin />
                ) : (
                  <ToolbarOverflowMenu
                    initiativeId={initiativeId}
                    supportsSmartChips={supportsEntityMentions}
                    variant={variant}
                  />
                )}
              </div>
            </>
          )}
        </ToolbarPlugin>
      )}
      <div className="relative grow">
        <div className="relative">
          {/* Horizontal padding lives on this wrapper, not the ContentEditable root:
              lexical 0.45 writes an inline `padding-inline-start` on the editable
              (from node indent) which would override a `px-*` class to 0. Its guard
              is `indent === 0`, but our nodes' __indent is `undefined`, so it emits
              `calc(undefined * ...)`. Revisit (move padding back) once lexical fixes
              the guard — expected in 0.46. */}
          {/* The writing gutter. A body whose container already pads it —
              a post in a card on the board — takes none of its own. */}
          <div className={cn(compact ? "px-0" : "px-8")} ref={onRef}>
            <ContentEditable
              placeholder={placeholder}
              className={cn(
                "ContentEditable__root relative block focus:outline-none",
                // A writing surface reserves a page to write on. A notice being
                // *read* is only as tall as what it says — a floor would put an
                // empty half-screen under every two-line post, on the board and
                // on its own page alike.
                variant === "post" && readOnly ? "py-2" : "min-h-72 pt-4 pb-14"
              )}
            />
          </div>
          {collaborative && <div ref={cursorsContainerRef} className="collaboration-cursors" />}
        </div>

        <TablePlugin hasCellMerge hasCellBackgroundColor />
        <TableActionMenuPlugin anchorElem={floatingAnchorElem} readOnly={readOnly} />
        <TabIndentationPlugin />

        <LegacyNodesPlugin />
        <MentionsPlugin initiativeId={initiativeId ?? undefined} />
        {supportsEntityMentions && <SmartChipRefsPlugin />}
        {supportsEntityMentions && <EntityMentionsPlugin initiativeId={initiativeId} />}
        <WikilinksPlugin
          initiativeId={initiativeId}
          onNavigate={onWikilinkNavigate}
          onCreateThing={onCreateReferencedThing}
        />
        <DraggableBlockPlugin anchorElem={floatingAnchorElem} />

        <AutoEmbedPlugin />
        <TwitterPlugin />
        <YouTubePlugin />

        <CodeActionMenuPlugin anchorElem={floatingAnchorElem} />

        <TabFocusPlugin />

        <ComponentPickerMenuPlugin
          baseOptions={[
            ParagraphPickerPlugin(),
            HeadingPickerPlugin({ n: 1 }),
            HeadingPickerPlugin({ n: 2 }),
            HeadingPickerPlugin({ n: 3 }),
            TablePickerPlugin(),
            CheckListPickerPlugin(),
            NumberedListPickerPlugin(),
            BulletedListPickerPlugin(),
            QuotePickerPlugin(),
            CodePickerPlugin(),
            DividerPickerPlugin(),
            EmbedsPickerPlugin({ embed: "tweet" }),
            EmbedsPickerPlugin({ embed: "youtube-video" }),
            ImagePickerPlugin(),
            // Live chips, offered where `#` is: prose only.
            ...(supportsEntityMentions ? SmartChipPickerPlugins(t, initiativeId) : []),
            ColumnsLayoutPickerPlugin(),
            AlignmentPickerPlugin({ alignment: "left" }),
            AlignmentPickerPlugin({ alignment: "center" }),
            AlignmentPickerPlugin({ alignment: "right" }),
            AlignmentPickerPlugin({ alignment: "justify" }),
          ]}
          dynamicOptionsFn={DynamicTablePickerPlugin}
        />

        {!readOnly && <ContextMenuPlugin />}
        {!readOnly && <DragDropPastePlugin />}
        <EmojiPickerPlugin />

        <LinkSanitizePlugin />
        <FloatingLinkEditorPlugin
          anchorElem={floatingAnchorElem}
          isLinkEditMode={isLinkEditMode}
          setIsLinkEditMode={setIsLinkEditMode}
        />
        <FloatingTextFormatToolbarPlugin
          anchorElem={floatingAnchorElem}
          setIsLinkEditMode={setIsLinkEditMode}
        />
      </div>
      {showToolbar && (
        <ActionsPlugin>
          <div className="sticky bottom-0 z-10 clear-both flex items-center justify-between gap-2 overflow-auto border-t bg-muted p-1">
            <div className="flex flex-1 justify-start"></div>
            <div>
              {/* With a limit, what matters is how much is left; without one,
                  how much there is. */}
              {maxLength !== undefined ? (
                <CharacterLimitPlugin maxLength={maxLength} charset="UTF-16" />
              ) : (
                <CounterCharacterPlugin charset="UTF-16" />
              )}
            </div>
            <div className="flex flex-1 justify-end">
              {/* A notice keeps the count and nothing else. Importing a file,
                  toggling to Markdown source, switching to read-only and
                  clearing the whole body are document tools — on a board they
                  are five buttons under a paragraph nobody asked to typeset. */}
              {rich && (
                <>
                  <SpeechToTextPlugin />
                  <ImportExportPlugin />
                  <MarkdownTogglePlugin transformers={MARKDOWN_TRANSFORMERS} />
                  <EditModeTogglePlugin forceReadOnly={readOnly} />
                  <ClearEditorActionPlugin />
                  <TreeViewPlugin />
                </>
              )}
            </div>
          </div>
        </ActionsPlugin>
      )}
    </div>
  );
}
