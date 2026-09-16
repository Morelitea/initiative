import { EraserIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useClearFormatting } from "@/components/ui/editor/plugins/toolbar/toolbar-actions";

export function ClearFormattingToolbarPlugin() {
  const clearFormatting = useClearFormatting();
  const { t } = useTranslation("documents");

  return (
    <Button
      variant="outline"
      size="icon-sm"
      className="size-8!"
      onClick={clearFormatting}
      title={t("editor.clearFormatting")}
      aria-label={t("editor.clearFormatting")}
      type="button"
    >
      <EraserIcon className="size-4" />
    </Button>
  );
}
