import { useTranslation } from "react-i18next";
import { Columns3Icon } from "lucide-react";

import { InsertLayoutDialog } from "@/components/ui/editor/plugins/layout-plugin";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";

export function ColumnsLayoutPickerPlugin() {
  const { t } = useTranslation("documents");
  return new ComponentPickerOption(t("editor.columnsLayout"), {
    icon: <Columns3Icon className="size-4" />,
    keywords: ["columns", "layout", "grid"],
    onSelect: (_, editor, showModal) =>
      showModal(t("editor.insertColumnsLayout"), (onClose) => (
        <InsertLayoutDialog activeEditor={editor} onClose={onClose} />
      )),
  });
}
