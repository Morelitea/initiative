import { useTranslation } from "react-i18next";
import {
  AlignCenter,
  AlignJustify,
  AlignLeft,
  AlignRight,
  Code2,
  Link as LinkIcon,
  List,
  ListChecks,
  ListOrdered,
  IndentDecrease,
  IndentIncrease,
  MoreHorizontal,
} from "lucide-react";
import { REDO_COMMAND, UNDO_COMMAND } from "lexical";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Alignment, ListType } from "./editorToolbarUtils";
import { FONT_SIZE_OPTIONS } from "./editorToolbarUtils";

export interface EditorMobileOverflowMenuProps {
  fontSize: string;
  applyFontSize: (size: string) => void;
  isUnderline: boolean;
  toggleUnderline: () => void;
  isCodeBlock: boolean;
  toggleCodeBlock: () => void;
  listType: ListType;
  toggleList: (type: Extract<ListType, "bullet" | "number" | "check">) => void;
  indentSelection: () => void;
  outdentSelection: () => void;
  insertLink: () => void;
  alignment: Alignment;
  applyAlignment: (value: Alignment) => void;
  insertOptions: Array<{ label: string; action: () => void; disabled?: boolean }>;
  isInTable: boolean;
  insertTableRow: (position: "above" | "below") => void;
  insertTableColumn: (position: "left" | "right") => void;
  deleteTableRow: () => void;
  deleteTableColumn: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

export const EditorMobileOverflowMenu = ({
  fontSize,
  applyFontSize,
  isUnderline,
  toggleUnderline,
  isCodeBlock,
  toggleCodeBlock,
  listType,
  toggleList,
  indentSelection,
  outdentSelection,
  insertLink,
  alignment,
  applyAlignment,
  insertOptions,
  isInTable,
  insertTableRow,
  insertTableColumn,
  deleteTableRow,
  deleteTableColumn,
  canUndo,
  canRedo,
}: EditorMobileOverflowMenuProps) => {
  const [editor] = useLexicalComposerContext();
  const { t } = useTranslation("documents");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" size="icon" variant="ghost" aria-label={t("editor.moreFormatting")}>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64 space-y-4">
        <DropdownMenuLabel>{t("editor.formatting")}</DropdownMenuLabel>
        <div className="space-y-1">
          <span className="text-muted-foreground text-xs font-medium">{t("editor.fontSize")}</span>
          <Select value={fontSize} onValueChange={(value) => applyFontSize(value)}>
            <SelectTrigger>
              <SelectValue placeholder={t("editor.fontSize")} />
            </SelectTrigger>
            <SelectContent>
              {FONT_SIZE_OPTIONS.map((size) => (
                <SelectItem key={size} value={size}>
                  {size}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="icon"
            variant={isUnderline ? "secondary" : "ghost"}
            aria-label={t("editor.underline")}
            onClick={toggleUnderline}
          >
            <span className="font-semibold underline">U</span>
          </Button>
          <Button
            type="button"
            size="icon"
            variant={isCodeBlock ? "secondary" : "ghost"}
            aria-label={t("editor.codeBlock")}
            onClick={toggleCodeBlock}
          >
            <Code2 className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant={listType === "bullet" ? "secondary" : "ghost"}
            aria-label={t("editor.bulletedList")}
            onClick={() => toggleList("bullet")}
          >
            <List className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant={listType === "number" ? "secondary" : "ghost"}
            aria-label={t("editor.numberedList")}
            onClick={() => toggleList("number")}
          >
            <ListOrdered className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant={listType === "check" ? "secondary" : "ghost"}
            aria-label={t("editor.checklist")}
            onClick={() => toggleList("check")}
          >
            <ListChecks className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.indent")}
            onClick={indentSelection}
          >
            <IndentIncrease className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.outdent")}
            onClick={outdentSelection}
          >
            <IndentDecrease className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.insertLink")}
            onClick={insertLink}
          >
            <LinkIcon className="h-4 w-4" />
          </Button>
        </div>
        <div className="space-y-1">
          <span className="text-muted-foreground text-xs font-medium">{t("editor.alignment")}</span>
          <Select value={alignment} onValueChange={(value: Alignment) => applyAlignment(value)}>
            <SelectTrigger>
              <SelectValue placeholder={t("editor.alignment")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="left">
                <div className="flex items-center gap-2">
                  <AlignLeft className="h-4 w-4" />
                  {t("editor.alignLeft")}
                </div>
              </SelectItem>
              <SelectItem value="center">
                <div className="flex items-center gap-2">
                  <AlignCenter className="h-4 w-4" />
                  {t("editor.alignCenter")}
                </div>
              </SelectItem>
              <SelectItem value="right">
                <div className="flex items-center gap-2">
                  <AlignRight className="h-4 w-4" />
                  {t("editor.alignRight")}
                </div>
              </SelectItem>
              <SelectItem value="justify">
                <div className="flex items-center gap-2">
                  <AlignJustify className="h-4 w-4" />
                  {t("editor.alignJustify")}
                </div>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <span className="text-muted-foreground text-xs font-medium">{t("editor.insert")}</span>
          <div className="grid grid-cols-2 gap-2">
            {insertOptions.map((item) => (
              <Button
                key={item.label}
                type="button"
                size="sm"
                variant="outline"
                disabled={item.disabled}
                onClick={item.action}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </div>
        <div className="space-y-2">
          <div className="text-muted-foreground flex items-center justify-between text-xs font-medium">
            <span>{t("editor.tableActions")}</span>
            {!isInTable ? <span className="text-[10px]">{t("editor.selectTable")}</span> : null}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isInTable}
              onClick={() => insertTableRow("above")}
            >
              {t("editor.rowAbove")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isInTable}
              onClick={() => insertTableRow("below")}
            >
              {t("editor.rowBelow")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isInTable}
              onClick={() => insertTableColumn("left")}
            >
              {t("editor.columnLeft")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!isInTable}
              onClick={() => insertTableColumn("right")}
            >
              {t("editor.columnRight")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={!isInTable}
              onClick={deleteTableRow}
            >
              {t("editor.deleteRow")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={!isInTable}
              onClick={deleteTableColumn}
            >
              {t("editor.deleteColumn")}
            </Button>
          </div>
        </div>
        <DropdownMenuSeparator />
        {/* eslint-disable i18next/no-literal-string */}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.undo")}
            disabled={!canUndo}
            onClick={() => editor.dispatchCommand(UNDO_COMMAND, undefined)}
          >
            ↺
          </Button>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label={t("editor.redo")}
            disabled={!canRedo}
            onClick={() => editor.dispatchCommand(REDO_COMMAND, undefined)}
          >
            ↻
          </Button>
        </div>
        {/* eslint-enable i18next/no-literal-string */}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
