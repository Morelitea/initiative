import { useEffect, useState } from "react";
import {
  CHECK_LIST,
  ELEMENT_TRANSFORMERS,
  MULTILINE_ELEMENT_TRANSFORMERS,
  TEXT_FORMAT_TRANSFORMERS,
  TEXT_MATCH_TRANSFORMERS,
} from "@lexical/markdown";
// import { AutoFocusPlugin } from "@lexical/react/LexicalAutoFocusPlugin";
import { CheckListPlugin } from "@lexical/react/LexicalCheckListPlugin";
import { ClearEditorPlugin } from "@lexical/react/LexicalClearEditorPlugin";
import { ClickableLinkPlugin } from "@lexical/react/LexicalClickableLinkPlugin";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HashtagPlugin } from "@lexical/react/LexicalHashtagPlugin";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { HorizontalRulePlugin } from "@lexical/react/LexicalHorizontalRulePlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { MarkdownShortcutPlugin } from "@lexical/react/LexicalMarkdownShortcutPlugin";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { TabIndentationPlugin } from "@lexical/react/LexicalTabIndentationPlugin";
import { TablePlugin } from "@lexical/react/LexicalTablePlugin";

import { ContentEditable } from "@/components/ui/editor/editor-ui/content-editable";
import { ActionsPlugin } from "@/components/ui/editor/plugins/actions/actions-plugin";
// import { CharacterLimitPlugin } from "@/components/ui/editor/plugins/actions/character-limit-plugin";
import { ClearEditorActionPlugin } from "@/components/ui/editor/plugins/actions/clear-editor-plugin";
import { CounterCharacterPlugin } from "@/components/ui/editor/plugins/actions/counter-character-plugin";
import { EditModeTogglePlugin } from "@/components/ui/editor/plugins/actions/edit-mode-toggle-plugin";
import { ImportExportPlugin } from "@/components/ui/editor/plugins/actions/import-export-plugin";
import { MarkdownTogglePlugin } from "@/components/ui/editor/plugins/actions/markdown-toggle-plugin";
// import { MaxLengthPlugin } from "@/components/ui/editor/plugins/actions/max-length-plugin";
// import { ShareContentPlugin } from "@/components/ui/editor/plugins/actions/share-content-plugin";
import { SpeechToTextPlugin } from "@/components/ui/editor/plugins/actions/speech-to-text-plugin";
import { TreeViewPlugin } from "@/components/ui/editor/plugins/actions/tree-view-plugin";
import { AutoLinkPlugin } from "@/components/ui/editor/plugins/auto-link-plugin";
// import { AutocompletePlugin } from "@/components/ui/editor/plugins/autocomplete-plugin";
import { CodeActionMenuPlugin } from "@/components/ui/editor/plugins/code-action-menu-plugin";
import { CodeHighlightPlugin } from "@/components/ui/editor/plugins/code-highlight-plugin";
import { ComponentPickerMenuPlugin } from "@/components/ui/editor/plugins/component-picker-menu-plugin";
import { ContextMenuPlugin } from "@/components/ui/editor/plugins/context-menu-plugin";
import { DragDropPastePlugin } from "@/components/ui/editor/plugins/drag-drop-paste-plugin";
import { DraggableBlockPlugin } from "@/components/ui/editor/plugins/draggable-block-plugin";
import { AutoEmbedPlugin } from "@/components/ui/editor/plugins/embeds/auto-embed-plugin";
import { TwitterPlugin } from "@/components/ui/editor/plugins/embeds/twitter-plugin";
import { YouTubePlugin } from "@/components/ui/editor/plugins/embeds/youtube-plugin";
import { EmojiPickerPlugin } from "@/components/ui/editor/plugins/emoji-picker-plugin";
import { EmojisPlugin } from "@/components/ui/editor/plugins/emojis-plugin";
import { FloatingLinkEditorPlugin } from "@/components/ui/editor/plugins/floating-link-editor-plugin";
import { FloatingTextFormatToolbarPlugin } from "@/components/ui/editor/plugins/floating-text-format-plugin";
import { ImagesPlugin } from "@/components/ui/editor/plugins/images-plugin";
import { KeywordsPlugin } from "@/components/ui/editor/plugins/keywords-plugin";
import { LayoutPlugin } from "@/components/ui/editor/plugins/layout-plugin";
import { LinkPlugin } from "@/components/ui/editor/plugins/link-plugin";
import { ListMaxIndentLevelPlugin } from "@/components/ui/editor/plugins/list-max-indent-level-plugin";
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
import {
  DynamicTablePickerPlugin,
  TablePickerPlugin,
} from "@/components/ui/editor/plugins/picker/table-picker-plugin";
import { TabFocusPlugin } from "@/components/ui/editor/plugins/tab-focus-plugin";
import { BlockFormatDropDown } from "@/components/ui/editor/plugins/toolbar/block-format-toolbar-plugin";
import { FormatBulletedList } from "@/components/ui/editor/plugins/toolbar/block-format/format-bulleted-list";
import { FormatCheckList } from "@/components/ui/editor/plugins/toolbar/block-format/format-check-list";
import { FormatCodeBlock } from "@/components/ui/editor/plugins/toolbar/block-format/format-code-block";
import { FormatHeading } from "@/components/ui/editor/plugins/toolbar/block-format/format-heading";
import { FormatNumberedList } from "@/components/ui/editor/plugins/toolbar/block-format/format-numbered-list";
import { FormatParagraph } from "@/components/ui/editor/plugins/toolbar/block-format/format-paragraph";
import { FormatQuote } from "@/components/ui/editor/plugins/toolbar/block-format/format-quote";
import { BlockInsertPlugin } from "@/components/ui/editor/plugins/toolbar/block-insert-plugin";
import { InsertColumnsLayout } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-columns-layout";
import { InsertEmbeds } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-embeds";
import { InsertHorizontalRule } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-horizontal-rule";
import { InsertImage } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-image";
import { InsertTable } from "@/components/ui/editor/plugins/toolbar/block-insert/insert-table";
import { ClearFormattingToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/clear-formatting-toolbar-plugin";
import { CodeLanguageToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/code-language-toolbar-plugin";
import { ElementFormatToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/element-format-toolbar-plugin";
import { FontBackgroundToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-background-toolbar-plugin";
import { FontColorToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-color-toolbar-plugin";
// import { FontFamilyToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-family-toolbar-plugin";
import { FontFormatToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-format-toolbar-plugin";
import { FontSizeToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/font-size-toolbar-plugin";
import { HistoryToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/history-toolbar-plugin";
import { LinkToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/link-toolbar-plugin";
import { SubSuperToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/subsuper-toolbar-plugin";
import { ToolbarPlugin } from "@/components/ui/editor/plugins/toolbar/toolbar-plugin";
import { ToolbarOverflowMenu } from "@/components/ui/editor/plugins/toolbar/toolbar-overflow-menu";
// import { TypingPerfPlugin } from "@/components/ui/editor/plugins/typing-pref-plugin";
import { EMOJI } from "@/components/ui/editor/transformers/markdown-emoji-transformer";
import { HR } from "@/components/ui/editor/transformers/markdown-hr-transformer";
import { IMAGE } from "@/components/ui/editor/transformers/markdown-image-transformer";
import { TABLE } from "@/components/ui/editor/transformers/markdown-table-transformer";
import { TWEET } from "@/components/ui/editor/transformers/markdown-tweet-transformer";
import { Separator } from "@/components/ui/separator";
import type { UserPublic } from "@/types/api";

const placeholder = "Press / for commands...";
// const maxLength = 500;

export function Plugins({
  showToolbar = true,
  readOnly = false,
  mentionableUsers = [],
}: {
  showToolbar?: boolean;
  readOnly?: boolean;
  mentionableUsers?: UserPublic[];
}) {
  const [editor] = useLexicalComposerContext();
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
    <div className="relative">
      {showToolbar && (
        <ToolbarPlugin>
          {({ blockType }) => (
            <>
              {/* Desktop toolbar - all options inline */}
              <div className="bg-background vertical-align-middle sticky top-0 z-10 hidden flex-wrap items-center gap-2 overflow-auto border-b p-1 lg:flex">
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
                    <FontSizeToolbarPlugin />
                    <Separator orientation="vertical" className="h-7!" />
                    <FontFormatToolbarPlugin />
                    <Separator orientation="vertical" className="h-7!" />
                    <SubSuperToolbarPlugin />
                    <LinkToolbarPlugin setIsLinkEditMode={setIsLinkEditMode} />
                    <Separator orientation="vertical" className="h-7!" />
                    <ClearFormattingToolbarPlugin />
                    <Separator orientation="vertical" className="h-7!" />
                    <FontColorToolbarPlugin />
                    <FontBackgroundToolbarPlugin />
                    <Separator orientation="vertical" className="h-7!" />
                    <ElementFormatToolbarPlugin />
                    <Separator orientation="vertical" className="h-7!" />
                    <BlockInsertPlugin>
                      <InsertHorizontalRule />
                      <InsertImage />
                      <InsertTable />
                      <InsertColumnsLayout />
                      <InsertEmbeds />
                    </BlockInsertPlugin>
                  </>
                )}
              </div>

              {/* Compact toolbar - overflow menu */}
              <div className="bg-background vertical-align-middle sticky top-0 z-10 flex items-center gap-2 border-b p-1 lg:hidden">
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
                {blockType === "code" ? <CodeLanguageToolbarPlugin /> : <ToolbarOverflowMenu />}
              </div>
            </>
          )}
        </ToolbarPlugin>
      )}
      <div className="relative">
        {/* <AutoFocusPlugin /> */}
        <RichTextPlugin
          contentEditable={
            <div className="">
              <div className="" ref={onRef}>
                <ContentEditable
                  placeholder={placeholder}
                  className="ContentEditable__root relative block min-h-72 px-8 py-4 focus:outline-none"
                />
              </div>
            </div>
          }
          ErrorBoundary={LexicalErrorBoundary}
        />

        <ClickableLinkPlugin />
        <CheckListPlugin />
        <HorizontalRulePlugin />
        <TablePlugin hasCellMerge hasCellBackgroundColor />
        <ListPlugin />
        <TabIndentationPlugin />
        <HashtagPlugin />
        <HistoryPlugin />

        <MentionsPlugin mentionableUsers={mentionableUsers} />
        <DraggableBlockPlugin anchorElem={floatingAnchorElem} />
        <KeywordsPlugin />
        <EmojisPlugin />
        <ImagesPlugin />

        <LayoutPlugin />

        <AutoEmbedPlugin />
        <TwitterPlugin />
        <YouTubePlugin />

        <CodeHighlightPlugin />
        <CodeActionMenuPlugin anchorElem={floatingAnchorElem} />

        <MarkdownShortcutPlugin
          transformers={[
            TABLE,
            HR,
            IMAGE,
            EMOJI,
            TWEET,
            CHECK_LIST,
            ...ELEMENT_TRANSFORMERS,
            ...MULTILINE_ELEMENT_TRANSFORMERS,
            ...TEXT_FORMAT_TRANSFORMERS,
            ...TEXT_MATCH_TRANSFORMERS,
          ]}
        />
        {/* <TypingPerfPlugin /> */}
        <TabFocusPlugin />
        {/* <AutocompletePlugin /> */}
        <AutoLinkPlugin />
        <LinkPlugin />

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

        <FloatingLinkEditorPlugin
          anchorElem={floatingAnchorElem}
          isLinkEditMode={isLinkEditMode}
          setIsLinkEditMode={setIsLinkEditMode}
        />
        <FloatingTextFormatToolbarPlugin
          anchorElem={floatingAnchorElem}
          setIsLinkEditMode={setIsLinkEditMode}
        />

        <ListMaxIndentLevelPlugin />
      </div>
      {showToolbar && (
        <ActionsPlugin>
          <div className="bg-background sticky bottom-0 z-10 clear-both flex items-center justify-between gap-2 overflow-auto border-t p-1">
            <div className="flex flex-1 justify-start">
              {/* <MaxLengthPlugin maxLength={maxLength} />
              <CharacterLimitPlugin maxLength={maxLength} charset="UTF-16" /> */}
            </div>
            <div>
              <CounterCharacterPlugin charset="UTF-16" />
            </div>
            <div className="flex flex-1 justify-end">
              <SpeechToTextPlugin />
              {/* <ShareContentPlugin /> */}
              <ImportExportPlugin />
              <MarkdownTogglePlugin
                shouldPreserveNewLinesInMarkdown={true}
                transformers={[
                  TABLE,
                  HR,
                  IMAGE,
                  EMOJI,
                  TWEET,
                  CHECK_LIST,
                  ...ELEMENT_TRANSFORMERS,
                  ...MULTILINE_ELEMENT_TRANSFORMERS,
                  ...TEXT_FORMAT_TRANSFORMERS,
                  ...TEXT_MATCH_TRANSFORMERS,
                ]}
              />
              <EditModeTogglePlugin />
              <ClearEditorActionPlugin />
              <ClearEditorPlugin />
              <TreeViewPlugin />
            </div>
          </div>
        </ActionsPlugin>
      )}
    </div>
  );
}
