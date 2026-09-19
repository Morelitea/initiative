import { IS_APPLE } from "@lexical/utils";
import { RedoIcon, UndoIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { useHistoryActions } from "@/components/ui/editor/plugins/toolbar/toolbar-actions";

export function HistoryToolbarPlugin() {
  const { undo, redo, canUndo, canRedo } = useHistoryActions();
  const { t } = useTranslation("documents");

  return (
    <ButtonGroup>
      <Button
        disabled={!canUndo}
        onClick={undo}
        title={`${t("editor.undo")} (${IS_APPLE ? "⌘Z" : "Ctrl+Z"})`}
        type="button"
        aria-label={t("editor.undo")}
        size="icon"
        className="h-8! w-8!"
        variant="outline"
      >
        <UndoIcon className="size-4" />
      </Button>
      <Button
        disabled={!canRedo}
        onClick={redo}
        title={`${t("editor.redo")} (${IS_APPLE ? "⇧⌘Z" : "Ctrl+Y"})`}
        type="button"
        aria-label={t("editor.redo")}
        variant="outline"
        size="icon"
        className="h-8! w-8!"
      >
        <RedoIcon className="size-4" />
      </Button>
    </ButtonGroup>
  );
}
