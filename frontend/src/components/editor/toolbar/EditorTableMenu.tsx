import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface EditorTableMenuProps {
  isInTable: boolean;
  insertTableRow: (position: "above" | "below") => void;
  insertTableColumn: (position: "left" | "right") => void;
  deleteTableRow: () => void;
  deleteTableColumn: () => void;
}

export const EditorTableMenu = ({
  isInTable,
  insertTableRow,
  insertTableColumn,
  deleteTableRow,
  deleteTableColumn,
}: EditorTableMenuProps) => {
  const { t } = useTranslation("documents");

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" disabled={!isInTable}>
          {t("editor.table")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuLabel>{t("editor.tableActions")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!isInTable}
          onSelect={(event) => {
            event.preventDefault();
            insertTableRow("above");
          }}
        >
          {t("editor.insertRowAbove")}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!isInTable}
          onSelect={(event) => {
            event.preventDefault();
            insertTableRow("below");
          }}
        >
          {t("editor.insertRowBelow")}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!isInTable}
          onSelect={(event) => {
            event.preventDefault();
            insertTableColumn("left");
          }}
        >
          {t("editor.insertColumnLeft")}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!isInTable}
          onSelect={(event) => {
            event.preventDefault();
            insertTableColumn("right");
          }}
        >
          {t("editor.insertColumnRight")}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!isInTable}
          onSelect={(event) => {
            event.preventDefault();
            deleteTableRow();
          }}
        >
          {t("editor.deleteRow")}
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={!isInTable}
          onSelect={(event) => {
            event.preventDefault();
            deleteTableColumn();
          }}
        >
          {t("editor.deleteColumn")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
