import { useTranslation } from "react-i18next";
import { ImageIcon } from "lucide-react";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { InsertImageDialog } from "@/components/ui/editor/plugins/images-plugin";
import { SelectItem } from "@/components/ui/select";

export function InsertImage() {
  const { activeEditor, showModal } = useToolbarContext();
  const { t } = useTranslation("documents");

  return (
    <SelectItem
      value="image"
      onPointerUp={() => {
        showModal(t("editor.insertImage"), (onClose) => (
          <InsertImageDialog activeEditor={activeEditor} onClose={onClose} />
        ));
      }}
      className=""
    >
      <div className="flex items-center gap-1">
        <ImageIcon className="size-4" />
        <span>{t("editor.image")}</span>
      </div>
    </SelectItem>
  );
}
