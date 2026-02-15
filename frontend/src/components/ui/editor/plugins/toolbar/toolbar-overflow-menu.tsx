import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { INSERT_EMBED_COMMAND } from "@lexical/react/LexicalAutoEmbedPlugin";
import { $isDecoratorBlockNode } from "@lexical/react/LexicalDecoratorBlockNode";
import { INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/react/LexicalHorizontalRuleNode";
import { $isHeadingNode, $isQuoteNode } from "@lexical/rich-text";
import { $isTableSelection } from "@lexical/table";
import { $getNearestBlockElementAncestorOrThrow } from "@lexical/utils";
import { $patchStyleText } from "@lexical/selection";
import {
  $createParagraphNode,
  $getSelection,
  $isRangeSelection,
  $isTextNode,
  FORMAT_ELEMENT_COMMAND,
  FORMAT_TEXT_COMMAND,
  INDENT_CONTENT_COMMAND,
  OUTDENT_CONTENT_COMMAND,
} from "lexical";
import {
  AlignCenterIcon,
  AlignJustifyIcon,
  AlignLeftIcon,
  AlignRightIcon,
  BoldIcon,
  CodeIcon,
  Columns3Icon,
  ImageIcon,
  IndentDecreaseIcon,
  IndentIncreaseIcon,
  ItalicIcon,
  MinusIcon,
  MoreHorizontalIcon,
  PaletteIcon,
  PaintBucketIcon,
  RemoveFormattingIcon,
  StrikethroughIcon,
  SubscriptIcon,
  SuperscriptIcon,
  TableIcon,
  TwitterIcon,
  UnderlineIcon,
  YoutubeIcon,
} from "lucide-react";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { InsertImageDialog } from "@/components/ui/editor/plugins/images-plugin";
import { InsertLayoutDialog } from "@/components/ui/editor/plugins/layout-plugin";
import { InsertTableDialog } from "@/components/ui/editor/plugins/table-plugin";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuPortal,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function ToolbarOverflowMenu() {
  const { activeEditor, showModal } = useToolbarContext();
  const { t } = useTranslation("documents");

  const TEXT_COLORS = useMemo(
    () => [
      { label: t("editor.colorDefault"), value: "" },
      { label: t("editor.colorBlack"), value: "#000000" },
      { label: t("editor.colorGray"), value: "#6b7280" },
      { label: t("editor.colorRed"), value: "#ef4444" },
      { label: t("editor.colorOrange"), value: "#f97316" },
      { label: t("editor.colorYellow"), value: "#eab308" },
      { label: t("editor.colorGreen"), value: "#22c55e" },
      { label: t("editor.colorBlue"), value: "#3b82f6" },
      { label: t("editor.colorPurple"), value: "#a855f7" },
      { label: t("editor.colorPink"), value: "#ec4899" },
    ],
    [t]
  );

  const BG_COLORS = useMemo(
    () => [
      { label: t("editor.colorNone"), value: "" },
      { label: t("editor.colorGray"), value: "#f3f4f6" },
      { label: t("editor.colorRed"), value: "#fee2e2" },
      { label: t("editor.colorOrange"), value: "#ffedd5" },
      { label: t("editor.colorYellow"), value: "#fef9c3" },
      { label: t("editor.colorGreen"), value: "#dcfce7" },
      { label: t("editor.colorBlue"), value: "#dbeafe" },
      { label: t("editor.colorPurple"), value: "#f3e8ff" },
      { label: t("editor.colorPink"), value: "#fce7f3" },
    ],
    [t]
  );

  const clearFormatting = useCallback(() => {
    activeEditor.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection) || $isTableSelection(selection)) {
        const anchor = selection.anchor;
        const focus = selection.focus;
        const nodes = selection.getNodes();
        const extractedNodes = selection.extract();

        if (anchor.key === focus.key && anchor.offset === focus.offset) {
          return;
        }

        nodes.forEach((node, idx) => {
          if ($isTextNode(node)) {
            let textNode = node;
            if (idx === 0 && anchor.offset !== 0) {
              textNode = textNode.splitText(anchor.offset)[1] || textNode;
            }
            if (idx === nodes.length - 1) {
              textNode = textNode.splitText(focus.offset)[0] || textNode;
            }
            const extractedTextNode = extractedNodes[0];
            if (nodes.length === 1 && $isTextNode(extractedTextNode)) {
              textNode = extractedTextNode;
            }

            if (textNode.__style !== "") {
              textNode.setStyle("");
            }
            if (textNode.__format !== 0) {
              textNode.setFormat(0);
              $getNearestBlockElementAncestorOrThrow(textNode).setFormat("");
            }
          } else if ($isHeadingNode(node) || $isQuoteNode(node)) {
            node.replace($createParagraphNode(), true);
          } else if ($isDecoratorBlockNode(node)) {
            node.setFormat("");
          }
        });
      }
    });
  }, [activeEditor]);

  const applyTextColor = useCallback(
    (color: string) => {
      activeEditor.update(() => {
        const selection = $getSelection();
        if (selection !== null) {
          $patchStyleText(selection, { color: color || null });
        }
      });
    },
    [activeEditor]
  );

  const applyBgColor = useCallback(
    (color: string) => {
      activeEditor.update(() => {
        const selection = $getSelection();
        if (selection !== null) {
          $patchStyleText(selection, { "background-color": color || null });
        }
      });
    },
    [activeEditor]
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 px-2">
          <MoreHorizontalIcon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel>{t("editor.format")}</DropdownMenuLabel>
        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "bold")}
          >
            <BoldIcon className="mr-2 size-4" />
            {t("editor.bold")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "italic")}
          >
            <ItalicIcon className="mr-2 size-4" />
            {t("editor.italic")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "underline")}
          >
            <UnderlineIcon className="mr-2 size-4" />
            {t("editor.underline")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "strikethrough")}
          >
            <StrikethroughIcon className="mr-2 size-4" />
            {t("editor.strikethrough")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "code")}
          >
            <CodeIcon className="mr-2 size-4" />
            {t("editor.inlineCode")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "subscript")}
          >
            <SubscriptIcon className="mr-2 size-4" />
            {t("editor.subscript")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(FORMAT_TEXT_COMMAND, "superscript")}
          >
            <SuperscriptIcon className="mr-2 size-4" />
            {t("editor.superscript")}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={clearFormatting}>
            <RemoveFormattingIcon className="mr-2 size-4" />
            {t("editor.clearFormatting")}
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <PaletteIcon className="mr-2 size-4" />
            {t("editor.textColor")}
          </DropdownMenuSubTrigger>
          <DropdownMenuPortal>
            <DropdownMenuSubContent>
              {TEXT_COLORS.map((color) => (
                <DropdownMenuItem key={color.value} onClick={() => applyTextColor(color.value)}>
                  <div
                    className="mr-2 size-4 rounded border"
                    style={{ backgroundColor: color.value || "transparent" }}
                  />
                  {color.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuPortal>
        </DropdownMenuSub>

        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <PaintBucketIcon className="mr-2 size-4" />
            {t("editor.background")}
          </DropdownMenuSubTrigger>
          <DropdownMenuPortal>
            <DropdownMenuSubContent>
              {BG_COLORS.map((color) => (
                <DropdownMenuItem key={color.value} onClick={() => applyBgColor(color.value)}>
                  <div
                    className="mr-2 size-4 rounded border"
                    style={{ backgroundColor: color.value || "transparent" }}
                  />
                  {color.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuPortal>
        </DropdownMenuSub>

        <DropdownMenuSeparator />

        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <AlignLeftIcon className="mr-2 size-4" />
            {t("editor.align")}
          </DropdownMenuSubTrigger>
          <DropdownMenuPortal>
            <DropdownMenuSubContent>
              <DropdownMenuItem
                onClick={() => activeEditor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "left")}
              >
                <AlignLeftIcon className="mr-2 size-4" />
                {t("editor.alignLeft")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => activeEditor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "center")}
              >
                <AlignCenterIcon className="mr-2 size-4" />
                {t("editor.alignCenter")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => activeEditor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "right")}
              >
                <AlignRightIcon className="mr-2 size-4" />
                {t("editor.alignRight")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => activeEditor.dispatchCommand(FORMAT_ELEMENT_COMMAND, "justify")}
              >
                <AlignJustifyIcon className="mr-2 size-4" />
                {t("editor.alignJustify")}
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuPortal>
        </DropdownMenuSub>

        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(OUTDENT_CONTENT_COMMAND, undefined)}
          >
            <IndentDecreaseIcon className="mr-2 size-4" />
            {t("editor.outdent")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(INDENT_CONTENT_COMMAND, undefined)}
          >
            <IndentIncreaseIcon className="mr-2 size-4" />
            {t("editor.indent")}
          </DropdownMenuItem>
        </DropdownMenuGroup>

        <DropdownMenuSeparator />

        <DropdownMenuLabel>{t("editor.insert")}</DropdownMenuLabel>
        <DropdownMenuGroup>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined)}
          >
            <MinusIcon className="mr-2 size-4" />
            {t("editor.horizontalRule")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              showModal(t("editor.insertImage"), (onClose) => (
                <InsertImageDialog activeEditor={activeEditor} onClose={onClose} />
              ))
            }
          >
            <ImageIcon className="mr-2 size-4" />
            {t("editor.image")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              showModal(t("editor.insertTable"), (onClose) => (
                <InsertTableDialog activeEditor={activeEditor} onClose={onClose} />
              ))
            }
          >
            <TableIcon className="mr-2 size-4" />
            {t("editor.table")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() =>
              showModal(t("editor.insertColumnsLayout"), (onClose) => (
                <InsertLayoutDialog activeEditor={activeEditor} onClose={onClose} />
              ))
            }
          >
            <Columns3Icon className="mr-2 size-4" />
            {t("editor.columnsLayout")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(INSERT_EMBED_COMMAND, "youtube-video")}
          >
            <YoutubeIcon className="mr-2 size-4" />
            {t("editor.youtubeVideo")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => activeEditor.dispatchCommand(INSERT_EMBED_COMMAND, "tweet")}
          >
            <TwitterIcon className="mr-2 size-4" />
            {t("editor.tweet")}
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
