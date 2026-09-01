/**
 * One tool entity's comment thread, ready to drop at the bottom of that
 * entity's page.
 *
 * It takes the ENTITY, not a pile of fields pulled out of it: every tool's read
 * schema carries the same three facts a thread needs — its id, the initiative
 * it lives in, and whether its comments are switched off (`comments_disabled`,
 * which `tools_test.py` holds every tool to). Deriving them here means a tool
 * page says which tool and which row, and a seventh tool needs no new wiring at
 * all.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type {
  ListCommentsApiV1GGuildIdCommentsGetParams,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentSection } from "@/components/comments/CommentSection";
import { useComments, useCommentsCache } from "@/hooks/useComments";
import type { ToolCommentEntity } from "@/lib/tools";

interface ToolCommentsPanelProps {
  /** Which tool the entity belongs to — the comment target's field name. */
  tool: Tool;
  /** The tool entity itself, as its read schema returns it. */
  entity: ToolCommentEntity;
  canModerate?: boolean;
  title?: string;
  /** Called with +1/-1 when the thread grows or shrinks, for a page that shows
   *  a comment count of its own. */
  onCountChange?: (delta: number) => void;
}

export const ToolCommentsPanel = ({
  tool,
  entity,
  canModerate = false,
  title,
  onCountChange,
}: ToolCommentsPanelProps) => {
  const { t } = useTranslation("documents");

  const entityId = entity.id;
  const disabled = entity.comments_disabled ?? false;
  // A guild-level entity (an app-installed calendar) belongs to no initiative;
  // 0 is what the mention lookups read as "no initiative to search".
  const initiativeId = entity.initiative_id ?? 0;

  const params = useMemo<ListCommentsApiV1GGuildIdCommentsGetParams>(() => {
    const next: ListCommentsApiV1GGuildIdCommentsGetParams = {};
    next[`${tool}_id`] = entityId;
    return next;
  }, [tool, entityId]);

  const commentsQuery = useComments(params, {
    enabled: Number.isFinite(entityId) && !disabled,
  });
  // Write the new row straight into this thread's cache as well as
  // invalidating, so the comment appears under the box the moment it posts.
  const cache = useCommentsCache(params);

  if (disabled) return null;

  return (
    <div className="space-y-2">
      {commentsQuery.isError && (
        <p className="text-destructive text-sm">{t("comments.loadError")}</p>
      )}
      <CommentSection
        entityType={tool}
        entityId={entityId}
        comments={commentsQuery.data ?? []}
        isLoading={commentsQuery.isLoading}
        canModerate={canModerate}
        initiativeId={initiativeId}
        onCommentCreated={(comment) => {
          cache.addComment(comment);
          onCountChange?.(1);
        }}
        onCommentDeleted={(commentId) => {
          cache.removeComment(commentId);
          onCountChange?.(-1);
        }}
        onCommentUpdated={cache.updateComment}
        {...(title !== undefined ? { title } : {})}
      />
    </div>
  );
};
