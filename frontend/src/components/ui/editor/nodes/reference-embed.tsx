import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useLexicalEditable } from "@lexical/react/useLexicalEditable";
import { useNavigate } from "@tanstack/react-router";
import { $getNodeByKey, type NodeKey, type SerializedEditorState } from "lexical";
import { ChevronDown, Link2 } from "lucide-react";
import { createContext, lazy, Suspense, useContext, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { TaskDescription } from "@/components/tasks/TaskDescription";
import { Button } from "@/components/ui/button";
import {
  $isReferenceEmbedNode,
  $showAsLink,
} from "@/components/ui/editor/nodes/reference-embed-node";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useReferenceEmbed } from "@/hooks/useSmartChips";
import { entityRefTypeFor } from "@/lib/entityResolver";
import { guildPath } from "@/lib/guildUrl";
import { hasBody } from "@/lib/posts";
import { hitIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

// Lazy for the reason a post's body is, and because the editor is what draws
// this component: importing it here would make the two modules each other's.
const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
);

/**
 * How many embedded bodies this one is inside. An embedded page draws its own
 * embeds as their names only, so a page embedding itself — or two pages
 * embedding each other — stops one level down instead of going on forever.
 */
const EmbedDepth = createContext(0);

/** The deepest an embed draws a body at: one page inside another, no further. */
const MAX_BODY_DEPTH = 1;

/** What a prose embed says: the page itself, read-only, in a pane of its own. */
function EmbeddedBody({ body }: { body: Record<string, unknown> }) {
  const depth = useContext(EmbedDepth);
  return (
    <EmbedDepth.Provider value={depth + 1}>
      <div className="max-h-96 overflow-y-auto rounded-md border bg-background/60 px-3">
        <Suspense fallback={<Skeleton className="my-2 h-16 w-full" />}>
          <Editor
            editorSerializedState={body as unknown as SerializedEditorState}
            readOnly
            showToolbar={false}
            variant="post"
            compact
          />
        </Suspense>
      </div>
    </EmbedDepth.Provider>
  );
}

interface ReferenceEmbedProps {
  entityType: SearchEntityType;
  entityId: number;
  /** The name as it read when written, shown when the thing cannot be read. */
  fallback: string;
  /** Folded to its name, as the page saved it. */
  collapsed: boolean;
  nodeKey: NodeKey;
}

/**
 * What an embed draws inside its callout: the thing's name, which opens it,
 * and below it what the thing says about itself — its description, or for a
 * page, the page.
 *
 * A thing that cannot be read — deleted, or never shared with this reader —
 * keeps the name it had, dimmed, and says so; the two look the same on
 * purpose, as they do for a link.
 */
export function ReferenceEmbed({
  entityType,
  entityId,
  fallback,
  collapsed,
  nodeKey,
}: ReferenceEmbedProps) {
  const { t } = useTranslation(["documents", "search"]);
  const [editor] = useLexicalComposerContext();
  const editable = useLexicalEditable();
  const navigate = useNavigate();
  const guildId = useActiveGuildId();
  const { data: embed, isFetched } = useReferenceEmbed(entityType, entityId);
  const depth = useContext(EmbedDepth);
  // A reader who cannot edit the page folds it for themselves; the page's
  // own answer returns when they reload, or when somebody who can changes it.
  const [readerFolded, setReaderFolded] = useState<boolean | null>(null);
  const folded = editable ? collapsed : (readerFolded ?? collapsed);

  const refType = entityRefTypeFor(entityType);
  const reachable = embed != null && refType !== null;
  const Icon = hitIcon({
    entity_type: entityType,
    entity_id: entityId,
    initiative_id: null,
    tool: null,
    tool_id: null,
  });

  const showBody = Boolean(embed?.body && hasBody(embed.body) && depth < MAX_BODY_DEPTH);
  const foldable = showBody || Boolean(embed?.description);

  const toggleFolded = () => {
    if (!editable) {
      setReaderFolded(!folded);
      return;
    }
    editor.update(() => {
      const node = $getNodeByKey(nodeKey);
      if ($isReferenceEmbedNode(node)) node.setCollapsed(!folded);
    });
  };

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
          {foldable ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="-my-1 size-7 shrink-0"
              onClick={toggleFolded}
              aria-expanded={!folded}
              aria-label={t(folded ? "embeds.expand" : "embeds.collapse")}
              title={t(folded ? "embeds.expand" : "embeds.collapse")}
            >
              <ChevronDown className={cn("size-4 transition-transform", folded && "-rotate-90")} />
            </Button>
          ) : null}
        </div>
        {folded && foldable ? null : showBody && embed?.body ? (
          <EmbeddedBody body={embed.body} />
        ) : embed?.description ? (
          <TaskDescription content={embed.description} />
        ) : isFetched && !embed ? (
          <p className="text-muted-foreground text-sm">{t("references.unavailable")}</p>
        ) : null}
      </div>
    </>
  );
}
