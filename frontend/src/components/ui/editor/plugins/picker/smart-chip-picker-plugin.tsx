import type { TFunction } from "i18next";
import { CalendarClock, CircleDot, Flag, Gauge, User } from "lucide-react";
import type { JSX } from "react";

import { SmartChipKind } from "@/api/generated/initiativeAPI.schemas";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";
import { SmartChipInsertDialog } from "@/components/ui/editor/plugins/smart-chip-insert-dialog";
import { chipAspect, SMART_CHIP_KINDS } from "@/lib/smartChips";

/**
 * How each chip is offered in the `/` menu.
 *
 * Keyed by the generated pair, so a chip the server adds cannot be silently
 * missing here — `smart-chip-picker-plugin.test.ts` fails if one is.
 */
export const SMART_CHIP_MENU: Record<
  SmartChipKind,
  { labelKey: string; icon: JSX.Element; keywords: string[] }
> = {
  [SmartChipKind["task:status"]]: {
    labelKey: "smartChips.taskStatus",
    icon: <CircleDot className="size-4" />,
    keywords: ["status", "task", "state", "column", "chip", "done"],
  },
  [SmartChipKind["task:assignee"]]: {
    labelKey: "smartChips.taskAssignee",
    icon: <User className="size-4" />,
    keywords: ["assignee", "task", "who", "owner", "chip"],
  },
  [SmartChipKind["task:due"]]: {
    labelKey: "smartChips.taskDue",
    icon: <CalendarClock className="size-4" />,
    keywords: ["due", "task", "date", "deadline", "chip"],
  },
  [SmartChipKind["task:priority"]]: {
    labelKey: "smartChips.taskPriority",
    icon: <Flag className="size-4" />,
    keywords: ["priority", "task", "urgent", "chip"],
  },
  [SmartChipKind["counter:value"]]: {
    labelKey: "smartChips.counterValue",
    icon: <Gauge className="size-4" />,
    keywords: ["counter", "count", "number", "value", "chip"],
  },
  [SmartChipKind["calendar_event:when"]]: {
    labelKey: "smartChips.eventWhen",
    icon: <CalendarClock className="size-4" />,
    keywords: ["event", "when", "date", "calendar", "chip"],
  },
};

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
