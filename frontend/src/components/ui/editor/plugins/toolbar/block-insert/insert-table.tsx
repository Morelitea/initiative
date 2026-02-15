import { useTranslation } from "react-i18next";
import { TableIcon } from "lucide-react";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { InsertTableDialog } from "@/components/ui/editor/plugins/table-plugin";
import { SelectItem } from "@/components/ui/select";

export function InsertTable() {
  const { activeEditor, showModal } = useToolbarContext();
  const { t } = useTranslation("documents");

  return (
    <SelectItem
      value="table"
      onPointerUp={() =>
        showModal(t("editor.insertTable"), (onClose) => (
          <InsertTableDialog activeEditor={activeEditor} onClose={onClose} />
        ))
      }
      className=""
    >
      <div className="flex items-center gap-1">
        <TableIcon className="size-4" />
        <span>{t("editor.table")}</span>
      </div>
    </SelectItem>
  );
}
