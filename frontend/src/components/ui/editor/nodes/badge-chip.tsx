import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { BadgeKind } from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useBadgeState } from "@/hooks/useDocumentBadges";
import { badgeDisplay, badgeEntityType, badgeRef } from "@/lib/badges";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface BadgeChipProps {
  badgeKind: BadgeKind;
  entityId: number;
  /** The label stored in the document, shown when the thing cannot be read. */
  fallback: string;
}

/**
 * The chip itself.
 *
 * Reads from the page's one badge request rather than making its own, so a
 * document with thirty of these still makes a single call.
 */
export function BadgeChip({ badgeKind, entityId, fallback }: BadgeChipProps) {
  const { t, i18n } = useTranslation("documents");
  const navigate = useNavigate();
  const guildId = useActiveGuildId();
  const state = useBadgeState(badgeRef(badgeKind, entityId));

  const display = badgeDisplay(
    fallback,
    state,
    (iso) => new Date(iso).toLocaleDateString(i18n.language, { month: "short", day: "numeric" }),
    t("badges.none")
  );

  const refType = entityRefTypeFor(badgeEntityType(badgeKind));
  const open = () => {
    if (!refType) return;
    void navigate({ to: guildPath(guildId, entityRefRoute(refType, entityId)) });
  };

  return (
    <button
      type="button"
      onClick={open}
      disabled={!refType}
      title={fallback}
      className={cn(
        "mx-0.5 inline-flex items-center rounded px-1.5 py-0.5 align-baseline font-medium text-xs",
        display.className,
        refType ? "cursor-pointer hover:brightness-95" : "cursor-default"
      )}
      // A status carries a colour its project chose, which beats any tone.
      style={
        display.color ? { backgroundColor: `${display.color}26`, color: display.color } : undefined
      }
    >
      {display.text}
    </button>
  );
}
