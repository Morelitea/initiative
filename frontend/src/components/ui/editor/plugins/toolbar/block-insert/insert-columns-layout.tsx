import { useTranslation } from "react-i18next";
import { Columns3Icon } from "lucide-react";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { InsertLayoutDialog } from "@/components/ui/editor/plugins/layout-plugin";
import { SelectItem } from "@/components/ui/select";

export function InsertColumnsLayout() {
  const { activeEditor, showModal } = useToolbarContext();
  const { t } = useTranslation("documents");

  return (
    <SelectItem
      value="columns"
      onPointerUp={() =>
        showModal(t("editor.insertColumnsLayout"), (onClose) => (
          <InsertLayoutDialog activeEditor={activeEditor} onClose={onClose} />
        ))
      }
      className=""
    >
      <div className="flex items-center gap-1">
        <Columns3Icon className="size-4" />
        <span>{t("editor.columnsLayout")}</span>
      </div>
    </SelectItem>
  );
}
