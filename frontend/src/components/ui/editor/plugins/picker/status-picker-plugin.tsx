import type { TFunction } from "i18next";
import { Tag } from "lucide-react";

import { INSERT_STATUS_COMMAND } from "@/components/ui/editor/extensions/status-extension";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";

/** A status written by hand: a word in a coloured pill. */
export function StatusPickerPlugin(t: TFunction<"documents">) {
  return new ComponentPickerOption(t("editor.status"), {
    icon: <Tag className="size-4" />,
    keywords: ["status", "lozenge", "label", "badge", "pill"],
    onSelect: (_, editor) => editor.dispatchCommand(INSERT_STATUS_COMMAND, undefined),
  });
}
