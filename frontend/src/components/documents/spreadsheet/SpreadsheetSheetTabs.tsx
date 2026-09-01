import { ChevronDown, Plus } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { MAX_SHEET_NAME_LENGTH, type SheetId, type SheetMeta } from "@/lib/spreadsheet/sheets";
import { cn } from "@/lib/utils";

interface SpreadsheetSheetTabsProps {
  sheets: SheetMeta[];
  activeSheetId: SheetId | null;
  readOnly: boolean;
  /** False once the workbook is at its sheet cap — the add button stays
   *  visible but inert so the ceiling is discoverable. */
  canAdd: boolean;
  onSelect: (id: SheetId) => void;
  onAdd: () => void;
  onRename: (id: SheetId, name: string) => void;
  onDelete: (id: SheetId) => void;
  onDuplicate: (id: SheetId) => void;
  onMove: (id: SheetId, delta: number) => void;
}

/**
 * The strip of sheet tabs along the bottom of the grid.
 *
 * Every action reachable by right-click is also on a per-tab dropdown, so
 * the whole feature works on a touch screen where there is no right-click:
 * tap to switch, tap the chevron on the active tab for the menu, and
 * double-tap (or "Rename" from that menu) to edit the name in place.
 * Reordering is a menu action rather than a drag for the same reason.
 */
export const SpreadsheetSheetTabs = ({
  sheets,
  activeSheetId,
  readOnly,
  canAdd,
  onSelect,
  onAdd,
  onRename,
  onDelete,
  onDuplicate,
  onMove,
}: SpreadsheetSheetTabsProps) => {
  const { t } = useTranslation(["documents", "common"]);
  // The sheet being renamed and its draft are separate pieces of state on
  // purpose: the effect below selects the input's text, and it must run
  // when the rename *starts*, not on every keystroke — a combined
  // ``{ id, draft }`` object changes identity on each character typed,
  // which re-selected the whole name and made the next keystroke replace
  // everything the user had typed so far.
  const [renamingId, setRenamingId] = useState<SheetId | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);
  const activeTabRef = useRef<HTMLDivElement>(null);

  const startRename = (sheet: SheetMeta) => {
    setRenamingId(sheet.id);
    setRenameDraft(sheet.name);
  };

  useEffect(() => {
    if (renamingId) renameInputRef.current?.select();
  }, [renamingId]);

  // Keep the active tab on screen when it changes from elsewhere — a
  // committed cross-sheet formula switches back to the sheet it lives on,
  // which may be scrolled out of the strip.
  useEffect(() => {
    activeTabRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeSheetId]);

  const commitRename = () => {
    if (!renamingId) return;
    const trimmed = renameDraft.trim();
    if (trimmed) onRename(renamingId, trimmed);
    setRenamingId(null);
  };

  const handleRenameKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      commitRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setRenamingId(null);
    }
  };

  return (
    <div
      className="flex shrink-0 items-center gap-1 overflow-x-auto border-border border-t bg-muted/20 px-2 py-1"
      role="tablist"
      aria-label={t("documents:spreadsheet.sheets.tablist")}
    >
      {!readOnly && (
        <button
          type="button"
          onClick={onAdd}
          disabled={!canAdd}
          title={
            canAdd
              ? t("documents:spreadsheet.sheets.add")
              : t("documents:spreadsheet.sheets.maxReached")
          }
          aria-label={t("documents:spreadsheet.sheets.add")}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
        >
          <Plus className="h-4 w-4" />
        </button>
      )}

      {sheets.map((sheet, index) => {
        const isActive = sheet.id === activeSheetId;
        const isRenaming = renamingId === sheet.id;
        return (
          <div
            key={sheet.id}
            ref={isActive ? activeTabRef : null}
            className={cn(
              "flex shrink-0 items-center rounded-t border-border border-x border-t",
              isActive ? "bg-background font-medium text-foreground" : "bg-muted/40"
            )}
          >
            {isRenaming ? (
              <input
                ref={renameInputRef}
                value={renameDraft}
                maxLength={MAX_SHEET_NAME_LENGTH}
                // biome-ignore lint/a11y/noAutofocus: the input replaces the tab the user just chose to rename
                autoFocus
                aria-label={t("documents:spreadsheet.sheets.renameLabel")}
                onChange={(e) => setRenameDraft(e.target.value)}
                onKeyDown={handleRenameKeyDown}
                onBlur={commitRename}
                className="w-28 bg-transparent px-2 py-1 text-sm outline-none ring-1 ring-primary ring-inset"
              />
            ) : (
              <button
                type="button"
                role="tab"
                aria-selected={isActive}
                onClick={() => onSelect(sheet.id)}
                onDoubleClick={() => {
                  if (!readOnly) startRename(sheet);
                }}
                className="max-w-48 truncate px-3 py-1 text-sm"
              >
                {sheet.name}
              </button>
            )}

            {!readOnly && !isRenaming && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    aria-label={t("documents:spreadsheet.sheets.menu", { name: sheet.name })}
                    className="flex h-7 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
                  >
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuItem onSelect={() => startRename(sheet)}>
                    {t("documents:spreadsheet.sheets.rename")}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={() => onDuplicate(sheet.id)}>
                    {t("documents:spreadsheet.sheets.duplicate")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem disabled={index === 0} onSelect={() => onMove(sheet.id, -1)}>
                    {t("documents:spreadsheet.sheets.moveLeft")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    disabled={index === sheets.length - 1}
                    onSelect={() => onMove(sheet.id, 1)}
                  >
                    {t("documents:spreadsheet.sheets.moveRight")}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    disabled={sheets.length <= 1}
                    onSelect={() => onDelete(sheet.id)}
                    className="text-destructive focus:text-destructive"
                  >
                    {t("documents:spreadsheet.sheets.delete")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
        );
      })}
    </div>
  );
};
