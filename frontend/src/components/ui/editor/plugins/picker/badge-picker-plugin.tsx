import type { TFunction } from "i18next";
import { CalendarClock, CircleDot, Flag, Gauge, User } from "lucide-react";
import type { JSX } from "react";

import { BadgeKind } from "@/api/generated/initiativeAPI.schemas";
import { BadgeInsertDialog } from "@/components/ui/editor/plugins/badge-insert-dialog";
import { ComponentPickerOption } from "@/components/ui/editor/plugins/picker/component-picker-option";
import { BADGE_KINDS, badgeAspect } from "@/lib/badges";

/**
 * How each badge is offered in the `/` menu.
 *
 * Keyed by the generated pair, so a badge the server adds cannot be silently
 * missing here — `badges.test.ts` fails if one is.
 */
export const BADGE_MENU: Record<
  BadgeKind,
  { labelKey: string; icon: JSX.Element; keywords: string[] }
> = {
  [BadgeKind["task:status"]]: {
    labelKey: "badges.taskStatus",
    icon: <CircleDot className="size-4" />,
    keywords: ["status", "task", "state", "column", "badge", "done"],
  },
  [BadgeKind["task:assignee"]]: {
    labelKey: "badges.taskAssignee",
    icon: <User className="size-4" />,
    keywords: ["assignee", "task", "who", "owner", "badge"],
  },
  [BadgeKind["task:due"]]: {
    labelKey: "badges.taskDue",
    icon: <CalendarClock className="size-4" />,
    keywords: ["due", "task", "date", "deadline", "badge"],
  },
  [BadgeKind["task:priority"]]: {
    labelKey: "badges.taskPriority",
    icon: <Flag className="size-4" />,
    keywords: ["priority", "task", "urgent", "badge"],
  },
  [BadgeKind["counter:value"]]: {
    labelKey: "badges.counterValue",
    icon: <Gauge className="size-4" />,
    keywords: ["counter", "count", "number", "value", "badge"],
  },
  [BadgeKind["calendar_event:when"]]: {
    labelKey: "badges.eventWhen",
    icon: <CalendarClock className="size-4" />,
    keywords: ["event", "when", "date", "calendar", "badge"],
  },
};

/**
 * One `/` entry per badge, built from the generated list.
 *
 * `initiativeId` is what a badge may point at: the same initiative the document
 * belongs to, so a chip cannot name work its readers cannot open.
 */
export function BadgePickerPlugins(
  t: TFunction<"documents">,
  initiativeId: number | null
): ComponentPickerOption[] {
  return BADGE_KINDS.map((kind) => {
    const entry = BADGE_MENU[kind];
    const title = t(entry.labelKey as never);
    return new ComponentPickerOption(title, {
      icon: entry.icon,
      keywords: [...entry.keywords, badgeAspect(kind)],
      onSelect: (_, editor, showModal) =>
        showModal(title, (onClose) => (
          <BadgeInsertDialog
            badgeKind={kind}
            initiativeId={initiativeId}
            activeEditor={editor}
            onClose={onClose}
          />
        )),
    });
  });
}
