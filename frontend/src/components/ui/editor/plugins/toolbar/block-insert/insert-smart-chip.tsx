import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { SmartChipInsertDialog } from "@/components/ui/editor/plugins/smart-chip-insert-dialog";
import { SelectItem } from "@/components/ui/select";

/**
 * "Smart chip" in the toolbar's insert menu.
 *
 * The `/` menu offers one entry per fact, because someone typing `/due` already
 * knows what they want. From the toolbar there is nothing typed to go on, so
 * the dialog asks for the thing first and the fact after.
 */
export function InsertSmartChip({ initiativeId }: { initiativeId: number | null }) {
  const { activeEditor, showModal } = useToolbarContext();
  const { t } = useTranslation("documents");

  return (
    <SelectItem
      value="smart-chip"
      onPointerUp={() => {
        showModal(t("smartChips.insert"), (onClose) => (
          <SmartChipInsertDialog
            initiativeId={initiativeId}
            activeEditor={activeEditor}
            onClose={onClose}
          />
        ));
      }}
    >
      <div className="flex items-center gap-1">
        <Sparkles className="size-4" />
        <span>{t("smartChips.insert")}</span>
      </div>
    </SelectItem>
  );
}
