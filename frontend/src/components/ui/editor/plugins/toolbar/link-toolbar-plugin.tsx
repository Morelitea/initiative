import { $isLinkNode } from "@lexical/link";
import {
  $isRangeSelection,
  type BaseSelection,
  COMMAND_PRIORITY_NORMAL,
  KEY_MODIFIER_COMMAND,
} from "lexical";
import { LinkIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useToolbarContext } from "@/components/ui/editor/context/toolbar-context";
import { useUpdateToolbarHandler } from "@/components/ui/editor/editor-hooks/use-update-toolbar";
import { useToggleLink } from "@/components/ui/editor/plugins/toolbar/toolbar-actions";
import { getSelectedNode } from "@/components/ui/editor/utils/get-selected-node";
import { Toggle } from "@/components/ui/toggle";

export function LinkToolbarPlugin({
  setIsLinkEditMode,
}: {
  setIsLinkEditMode: (isEditMode: boolean) => void;
}) {
  const { activeEditor } = useToolbarContext();
  const { t } = useTranslation("documents");
  const [isLink, setIsLink] = useState(false);
  const toggleLink = useToggleLink(setIsLinkEditMode);

  const $updateToolbar = (selection: BaseSelection) => {
    if ($isRangeSelection(selection)) {
      const node = getSelectedNode(selection);
      setIsLink($isLinkNode(node.getParent()) || $isLinkNode(node));
    }
  };

  useUpdateToolbarHandler($updateToolbar);

  useEffect(() => {
    return activeEditor.registerCommand(
      KEY_MODIFIER_COMMAND,
      (payload: KeyboardEvent) => {
        const { code, ctrlKey, metaKey } = payload;
        if (code !== "KeyK" || !(ctrlKey || metaKey)) return false;
        payload.preventDefault();
        toggleLink();
        return true;
      },
      COMMAND_PRIORITY_NORMAL
    );
  }, [activeEditor, toggleLink]);

  return (
    <Toggle
      variant="outline"
      size="sm"
      className="size-8!"
      pressed={isLink}
      aria-label={t("editor.insertLink")}
      onClick={toggleLink}
    >
      <LinkIcon className="h-4 w-4" />
    </Toggle>
  );
}
