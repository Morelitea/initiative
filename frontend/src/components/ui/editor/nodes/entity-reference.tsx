import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useReferenceTitle } from "@/hooks/useSmartChips";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";
import { hitIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface EntityReferenceProps {
  entityType: SearchEntityType;
  entityId: number;
  /** The name as it read when written. What an export shows, and what stands
   *  in when the thing can no longer be read. */
  fallback: string;
  showIcon?: boolean;
}

/**
 * A named thing, inside prose.
 *
 * Renders what it is called **now**, read from the page's one reference
 * request. Renaming a task changes every sentence that mentions it, in every
 * document and every comment, with none of them edited.
 *
 * A thing that cannot be read — deleted, or never shared with this reader —
 * shows the name it had, dimmed and going nowhere. Gone and out of reach look
 * the same on purpose: the server does not distinguish them either.
 */
export function EntityReference({
  entityType,
  entityId,
  fallback,
  showIcon = true,
}: EntityReferenceProps) {
  const { t } = useTranslation("documents");
  const navigate = useNavigate();
  const guildId = useActiveGuildId();
  const live = useReferenceTitle(entityType, entityId);

  const refType = entityRefTypeFor(entityType);
  const reachable = live !== undefined && refType !== null;
  const label = live ?? fallback ?? t("references.gone");
  const Icon = hitIcon({
    entity_type: entityType,
    entity_id: entityId,
    initiative_id: null,
    tool: null,
    tool_id: null,
  });

  const shared = "mx-0.5 inline-flex items-baseline gap-1 rounded px-1 align-baseline";

  if (!reachable) {
    return (
      <span
        className={cn(shared, "bg-muted/60 text-muted-foreground/80")}
        title={t("references.unavailable")}
      >
        {label}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void navigate({ to: guildPath(guildId, entityRefRoute(refType, entityId)) })}
      className={cn(
        shared,
        "cursor-pointer bg-primary/10 font-medium text-primary hover:bg-primary/20"
      )}
    >
      {showIcon && <Icon className="size-3 shrink-0 self-center" />}
      {label}
    </button>
  );
}
