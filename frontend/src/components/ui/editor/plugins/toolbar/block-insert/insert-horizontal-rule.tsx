import { INSERT_HORIZONTAL_RULE_COMMAND } from "@lexical/react/LexicalHorizontalRuleNode";
import { useTranslation } from "react-i18next";
import { ScissorsIcon } from "lucide-react";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { SelectItem } from "@/components/ui/select";

export function InsertHorizontalRule() {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("documents");

  return (
    <SelectItem
      value="horizontal-rule"
      onPointerUp={() => activeEditor.dispatchCommand(INSERT_HORIZONTAL_RULE_COMMAND, undefined)}
      className=""
    >
      <div className="flex items-center gap-1">
        <ScissorsIcon className="size-4" />
        <span>{t("editor.horizontalRule")}</span>
      </div>
    </SelectItem>
  );
}
