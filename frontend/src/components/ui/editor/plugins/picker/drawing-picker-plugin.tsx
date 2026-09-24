import type { TFunction } from "i18next";
import { PenTool } from "lucide-react";

import { INSERT_EXCALIDRAW_COMMAND } from "@/components/ui/editor/extensions/excalidraw-extension";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";

/** A drawing, drawn on the spot. */
export function DrawingPickerPlugin(t: TFunction<"documents">) {
  return new ComponentPickerOption(t("editor.drawing"), {
    icon: <PenTool className="size-4" />,
    keywords: ["drawing", "whiteboard", "excalidraw", "diagram", "sketch"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_EXCALIDRAW_COMMAND, undefined),
  });
}
