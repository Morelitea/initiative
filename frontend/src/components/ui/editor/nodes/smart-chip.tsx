import { useNavigate } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SmartChipKind } from "@/api/generated/initiativeAPI.schemas";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useChipState, useReferenceTitle } from "@/hooks/useSmartChips";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";
import { hitIcon } from "@/lib/searchResults";
import { chipAspect, chipDisplay, chipEntityType, chipRef } from "@/lib/smartChips";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface SmartChipProps {
  chipKind: SmartChipKind;
  entityId: number;
  /** The label stored in the document, shown when the thing cannot be read. */
  fallback: string;
}

/**
 * The chip itself.
 *
 * Inline it is the reading and nothing else — `In Progress`, `42 / 100`,
 * `Sep 12` — because a sentence that already names the task should not name it
 * twice. What the reading is ABOUT is one hover away: the card says what the
 * thing is called now, what kind of thing it is, and which fact this is.
 *
 * Reads from the page's one request rather than making its own, so a document
 * with thirty of these still makes a single call.
 */
export function SmartChip({ chipKind, entityId, fallback }: SmartChipProps) {
  const { t, i18n } = useTranslation(["documents", "search"]);
  const navigate = useNavigate();
  const guildId = useActiveGuildId();
  const state = useChipState(chipRef(chipKind, entityId));

  const entityType = chipEntityType(chipKind);
  // The name comes from the same request the reading did: a chip asks about
  // `task:12` as well as `task:12:status`, so the card names what the thing is
  // called now rather than what it was called when the chip was inserted.
  const liveTitle = useReferenceTitle(entityType, entityId);

  const display = chipDisplay(
    fallback,
    state,
    (iso) => new Date(iso).toLocaleDateString(i18n.language, { month: "short", day: "numeric" }),
    t("smartChips.none")
  );

  const refType = entityRefTypeFor(entityType);
  // Something that could not be read has nowhere to go — the same answer
  // whether it was deleted or was never this reader's to see.
  const reachable = refType !== null && display.live;
  const open = () => {
    if (!refType || !reachable) return;
    void navigate({ to: guildPath(guildId, entityRefRoute(refType, entityId)) });
  };

  const Icon = hitIcon({
    entity_type: entityType,
    entity_id: entityId,
    initiative_id: null,
    tool: null,
    tool_id: null,
  });

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          onClick={open}
          // `aria-disabled` rather than `disabled`: a disabled button takes no
          // pointer events, and the card is what explains why this one is dim.
          aria-disabled={!reachable}
          className={cn(
            "mx-0.5 inline-flex items-center rounded px-1.5 py-0.5 align-baseline font-medium text-xs",
            display.className,
            reachable ? "cursor-pointer hover:brightness-95" : "cursor-default"
          )}
          // A status carries a colour its project chose, which beats any tone.
          style={
            display.color
              ? { backgroundColor: `${display.color}26`, color: display.color }
              : undefined
          }
        >
          {display.text}
        </button>
      </HoverCardTrigger>
      <HoverCardContent align="start" className="w-auto max-w-72 p-3">
        <div className="flex items-start gap-2">
          <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 space-y-1">
            <p className="truncate font-medium text-sm leading-tight">{liveTitle ?? fallback}</p>
            <p className="text-muted-foreground text-xs">
              {t(`search:types.${entityType}` as never)}
              {" · "}
              {t(`smartChips.aspects.${chipAspect(chipKind)}` as never)}
            </p>
            {reachable ? (
              <p className="flex items-center gap-1 text-primary text-xs">
                <ArrowUpRight className="size-3 shrink-0" />
                {t("smartChips.openHint")}
              </p>
            ) : (
              <p className="text-muted-foreground text-xs">{t("references.unavailable")}</p>
            )}
          </div>
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}
