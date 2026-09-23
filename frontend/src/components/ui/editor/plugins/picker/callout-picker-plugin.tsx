import type { TFunction } from "i18next";

import { INSERT_CALLOUT_COMMAND } from "@/components/ui/editor/extensions/callout-extension";
import { CALLOUT_VARIANTS } from "@/components/ui/editor/nodes/callout-node";
import { CalloutIcon } from "@/components/ui/editor/plugins/callout-icon";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";

/** One "/" entry per kind of callout, so the kind is chosen as it is made. */
export function CalloutPickerPlugins(t: TFunction<"documents">) {
  return CALLOUT_VARIANTS.map(
    (variant) =>
      new ComponentPickerOption(
        t("editor.calloutOf", { kind: t(`editor.calloutKinds.${variant}`) }),
        {
          icon: <CalloutIcon variant={variant} className="size-4" />,
          keywords: ["callout", "panel", "admonition", "alert", variant],
          onSelect: (_, editor) => editor.dispatchCommand(INSERT_CALLOUT_COMMAND, variant),
        }
      )
  );
}
