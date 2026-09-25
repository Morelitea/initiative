import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { useNavigate } from "@tanstack/react-router";
import { $getNodeByKey, type NodeKey } from "lexical";
import { Link2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { Button } from "@/components/ui/button";
import {
  $isReferenceEmbedNode,
  $showAsLink,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useReferenceEmbed } from "@/hooks/useSmartChips";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";
import { hitIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

interface ReferenceEmbedProps {
  entityType: SearchEntityType;
  entityId: number;
  /** The name as it read when written, shown when the thing cannot be read. */
  fallback: string;
  nodeKey: NodeKey;
}

/**
 * What an embed draws inside its callout: the thing's name, which opens it,
 * and below it what the thing says about itself.
 *
 * A thing that cannot be read — deleted, or never shared with this reader —
 * keeps the name it had, dimmed, and says so; the two look the same on
 * purpose, as they do for a link.
 */
export function ReferenceEmbed({ entityType, entityId, fallback, nodeKey }: ReferenceEmbedProps) {
  const { t } = useTranslation(["documents", "search"]);
  const [editor] = useLexicalComposerContext();
  const editable = useLexicalEditable();
  const navigate = useNavigate();
  const guildId = useActiveGuildId();
  const { data: embed, isFetched } = useReferenceEmbed(entityType, entityId);

  const refType = entityRefTypeFor(entityType);
  const reachable = embed != null && refType !== null;
  const Icon = hitIcon({
    entity_type: entityType,
    entity_id: entityId,
    initiative_id: null,
    tool: null,
    tool_id: null,
  });

  const showAsLink = () =>
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isReferenceEmbedNode(node)) $showAsLink(node);
    });

  return (
    <>
      <span className="callout-icon" aria-hidden="true" />
      <div className="callout-body space-y-2">
        <div className="flex items-start gap-2">
          <Icon className="mt-1 size-4 shrink-0 text-muted-foreground" />
          <button
            type="button"
            onClick={() => {
              if (reachable && refType) {
                void navigate({ to: guildPath(guildId, entityRefRoute(refType, entityId)) });
              }
            }}
            aria-disabled={!reachable}
            className={cn(
              "min-w-0 flex-1 text-left font-semibold",
              reachable ? "cursor-pointer hover:underline" : "cursor-default text-muted-foreground"
            )}
          >
            {embed?.title ?? fallback}
          </button>
          <span className="shrink-0 pt-0.5 text-muted-foreground text-xs">
            {t(`search:types.${entityType}` as never)}
          </span>
          {editable ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="-my-1 size-7 shrink-0"
              onClick={showAsLink}
              aria-label={t("embeds.showAsLink")}
              title={t("embeds.showAsLink")}
            >
              <Link2 className="size-3.5" />
            </Button>
          ) : null}
        </div>
        {embed?.description ? (
          <TaskDescription content={embed.description} />
        ) : isFetched && !embed ? (
          <p className="text-muted-foreground text-sm">{t("references.unavailable")}</p>
        ) : null}
      </div>
    </>
  );
}
