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

  // Find the active table cell from the selection; only compute DOM position
  // when the cursor is actually inside a table to avoid unnecessary layout reads.
  const updatePosition = useCallback(() => {
    let cellKey: string | null = null;

    editor.getEditorState().read(() => {
      const selection = $getSelection();
      if (!$isRangeSelection(selection)) return;
      let node: ReturnType<typeof selection.anchor.getNode> | null = selection.anchor.getNode();
      while (node !== null) {
        if ($isTableCellNode(node)) {
          cellKey = node.getKey();
          return;
        }
        node = node.getParent();
      }
    });

    if (!cellKey) {
      setPosition((prev) => (prev === null ? prev : null));
      return;
    }

    const cellElement = editor.getElementByKey(cellKey);
    if (!cellElement) {
      setPosition((prev) => (prev === null ? prev : null));
      return;
    }

    const cellRect = cellElement.getBoundingClientRect();
    const anchorRect = anchorElem.getBoundingClientRect();
    setPosition({
      top: cellRect.top - anchorRect.top + 4,
      left: cellRect.right - anchorRect.left - 24,
    });
  }, [editor, anchorElem]);

  useEffect(() => {
    updatePosition();
    const unregister = editor.registerUpdateListener(() => updatePosition());
    anchorElem.addEventListener("scroll", updatePosition, true);
    return () => {
      unregister();
      anchorElem.removeEventListener("scroll", updatePosition, true);
    };
  }, [editor, updatePosition, anchorElem]);

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
