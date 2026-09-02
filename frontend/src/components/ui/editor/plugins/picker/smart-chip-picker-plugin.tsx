import type { TFunction } from "i18next";

import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";
import { SmartChipInsertDialog } from "@/components/ui/editor/plugins/smart-chip-insert-dialog";
import { SMART_CHIP_MENU } from "@/components/ui/editor/plugins/smart-chip-menu";
import { chipAspect, SMART_CHIP_KINDS } from "@/lib/smartChips";

/**
 * One `/` entry per chip, built from the generated list.
 *
 * `initiativeId` is what a chip may point at: the same initiative the document
 * belongs to, so a chip cannot name work its readers cannot open.
 */
export function SmartChipPickerPlugins(
  t: TFunction<"documents">,
  initiativeId: number | null
): ComponentPickerOption[] {
  return SMART_CHIP_KINDS.map((kind) => {
    const entry = SMART_CHIP_MENU[kind];
    const title = t(entry.labelKey as never);
    return new ComponentPickerOption(title, {
      icon: entry.icon,
      keywords: [...entry.keywords, chipAspect(kind)],
      onSelect: (_, editor, showModal) =>
        showModal(title, (onClose) => (
          <SmartChipInsertDialog
            chipKind={kind}
            initiativeId={initiativeId}
            activeEditor={editor}
            onClose={onClose}
          />
        )),
    });
  });
}
