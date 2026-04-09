import { useCallback, useEffect, useState, type CSSProperties, type ReactPortal } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import {
  $deleteTableColumnAtSelection,
  $deleteTableRowAtSelection,
  $getTableNodeFromLexicalNodeOrThrow,
  $insertTableColumnAtSelection,
  $insertTableRowAtSelection,
  $isTableCellNode,
  TableCellHeaderStates,
  type TableCellNode,
  type TableNode,
} from "@lexical/table";
import { $getSelection, $isRangeSelection } from "lexical";
import {
  ArrowDownToLine,
  ArrowLeftToLine,
  ArrowRightToLine,
  ArrowUpToLine,
  ChevronDown,
  Heading,
  Trash2,
} from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface MenuPosition {
  top: number;
  left: number;
}

function TableActionMenuContainer({ anchorElem }: { anchorElem: HTMLElement }) {
  const { t } = useTranslation("documents");
  const [editor] = useLexicalComposerContext();
  const [position, setPosition] = useState<MenuPosition | null>(null);

  // Read the active table cell from the current selection and update position.
  // Returns true if a table cell is currently selected.
  const updatePosition = useCallback(() => {
    let nextPosition: MenuPosition | null = null;

    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) {
        return;
      }
      // Walk up from the selection's anchor node to find a TableCellNode
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let cellNode: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          cellNode = node;
          break;
        }
        node = node.getParent();
      }
      if (!cellNode) {
        return;
      }

      // Compute screen position for the cell
      const cellElement = editor.getElementByKey(cellNode.getKey());
      if (!cellElement) {
        return;
      }
      const cellRect = cellElement.getBoundingClientRect();
      const anchorRect = anchorElem.getBoundingClientRect();
      // Anchor button to the top-right of the cell, slightly inset
      nextPosition = {
        top: cellRect.top - anchorRect.top + 4,
        left: cellRect.right - anchorRect.left - 24,
      };
    });

    setPosition(nextPosition);
  }, [editor, anchorElem]);

  useEffect(() => {
    // Initial position
    updatePosition();
    // React to selection changes and any editor updates
    return editor.registerUpdateListener(() => {
      updatePosition();
    });
  }, [editor, updatePosition]);

  // ── Action handlers ─────────────────────────────────────────────────────

  const insertRowAbove = useCallback(() => {
    editor.update(() => {
      $insertTableRowAtSelection(false);
    });
  }, [editor]);

  const insertRowBelow = useCallback(() => {
    editor.update(() => {
      $insertTableRowAtSelection(true);
    });
  }, [editor]);

  const insertColumnLeft = useCallback(() => {
    editor.update(() => {
      $insertTableColumnAtSelection(false);
    });
  }, [editor]);

  const insertColumnRight = useCallback(() => {
    editor.update(() => {
      $insertTableColumnAtSelection(true);
    });
  }, [editor]);

  const deleteRow = useCallback(() => {
    editor.update(() => {
      $deleteTableRowAtSelection();
    });
  }, [editor]);

  const deleteColumn = useCallback(() => {
    editor.update(() => {
      $deleteTableColumnAtSelection();
    });
  }, [editor]);

  const deleteTable = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let cellNode: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          cellNode = node;
          break;
        }
        node = node.getParent();
      }
      if (!cellNode) return;
      const tableNode: TableNode = $getTableNodeFromLexicalNodeOrThrow(cellNode);
      tableNode.remove();
    });
  }, [editor]);

  // Toggle the header state for the entire row containing the active cell
  const toggleHeaderRow = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let activeCell: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          activeCell = node;
          break;
        }
        node = node.getParent();
      }
      if (!activeCell) return;
      const rowNode = activeCell.getParent();
      if (!rowNode) return;
      // Apply toggleHeaderStyle to every cell in the row
      for (const child of rowNode.getChildren()) {
        if ($isTableCellNode(child)) {
          child.toggleHeaderStyle(TableCellHeaderStates.ROW);
        }
      }
    });
  }, [editor]);

  // Toggle the header state for the entire column containing the active cell
  const toggleHeaderColumn = useCallback(() => {
    editor.update(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      let activeCell: TableCellNode | null = null;
      while (node !== null) {
        if ($isTableCellNode(node)) {
          activeCell = node;
          break;
        }
        node = node.getParent();
      }
      if (!activeCell) return;
      const tableNode = $getTableNodeFromLexicalNodeOrThrow(activeCell);
      const columnIndex = activeCell.getParent()?.getChildren().indexOf(activeCell) ?? -1;
      if (columnIndex < 0) return;
      // For each row in the table, toggle the header style on the cell at columnIndex
      for (const rowNode of tableNode.getChildren()) {
        const cells = (
          rowNode as ReturnType<typeof tableNode.getChildren>[number] & {
            getChildren: () => Array<ReturnType<typeof tableNode.getChildren>[number]>;
          }
        ).getChildren();
        const cell = cells[columnIndex];
        if (cell && $isTableCellNode(cell)) {
          cell.toggleHeaderStyle(TableCellHeaderStates.COLUMN);
        }
      }
    });
  }, [editor]);

  if (!position) {
    return null;
  }

  const style: CSSProperties = {
    position: "absolute",
    top: `${position.top}px`,
    left: `${position.left}px`,
    zIndex: 20,
  };

  return (
    <div style={style}>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="bg-background hover:bg-accent text-muted-foreground inline-flex h-5 w-5 items-center justify-center rounded border shadow-sm outline-none"
          aria-label={t("editor.tableActions")}
        >
          <ChevronDown className="h-3 w-3" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuItem onSelect={insertRowAbove}>
            <ArrowUpToLine className="mr-2 h-4 w-4" />
            {t("editor.insertRowAbove")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={insertRowBelow}>
            <ArrowDownToLine className="mr-2 h-4 w-4" />
            {t("editor.insertRowBelow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={insertColumnLeft}>
            <ArrowLeftToLine className="mr-2 h-4 w-4" />
            {t("editor.insertColumnLeft")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={insertColumnRight}>
            <ArrowRightToLine className="mr-2 h-4 w-4" />
            {t("editor.insertColumnRight")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={deleteRow}>
            <Trash2 className="mr-2 h-4 w-4" />
            {t("editor.deleteRow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={deleteColumn}>
            <Trash2 className="mr-2 h-4 w-4" />
            {t("editor.deleteColumn")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={toggleHeaderRow}>
            <Heading className="mr-2 h-4 w-4" />
            {t("editor.toggleHeaderRow")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={toggleHeaderColumn}>
            <Heading className="mr-2 h-4 w-4" />
            {t("editor.toggleHeaderColumn")}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={deleteTable} className="text-destructive">
            <Trash2 className="mr-2 h-4 w-4" />
            {t("editor.deleteTable")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

export function TableActionMenuPlugin({
  anchorElem = null,
  readOnly = false,
}: {
  anchorElem: HTMLElement | null;
  readOnly?: boolean;
}): ReactPortal | null {
  if (!anchorElem || readOnly) {
    return null;
  }
  return createPortal(<TableActionMenuContainer anchorElem={anchorElem} />, anchorElem);
}
