/**
 * One tool entity's comment thread, ready to drop at the bottom of that
 * entity's page: it reads the thread for `<entity>_id` and hands it to the
 * shared CommentSection.
 */

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ListCommentsApiV1GGuildIdCommentsGetParams } from "@/api/generated/initiativeAPI.schemas";
import { type CommentEntity, CommentSection } from "@/components/comments/CommentSection";
import { useComments } from "@/hooks/useComments";

interface ToolCommentsPanelProps {
  entityType: CommentEntity;
  entityId: number;
  /** The entity's initiative. Guild-level entities (an app-installed calendar)
   *  pass 0 — mention suggestions are an initiative lookup and switch off. */
  initiativeId: number;
  canModerate?: boolean;
  title?: string;
}

export const ToolCommentsPanel = ({
  entityType,
  entityId,
  initiativeId,
  canModerate = false,
  title,
}: ToolCommentsPanelProps) => {
  const { t } = useTranslation("documents");

  const params = useMemo<ListCommentsApiV1GGuildIdCommentsGetParams>(() => {
    const next: ListCommentsApiV1GGuildIdCommentsGetParams = {};
    next[`${entityType}_id`] = entityId;
    return next;
  }, [entityType, entityId]);

  const commentsQuery = useComments(params, { enabled: Number.isFinite(entityId) });

  return (
    <div className="space-y-2">
      {commentsQuery.isError && (
        <p className="text-destructive text-sm">{t("comments.loadError")}</p>
      )}
      <CommentSection
        entityType={entityType}
        entityId={entityId}
        comments={commentsQuery.data ?? []}
        isLoading={commentsQuery.isLoading}
        canModerate={canModerate}
        initiativeId={initiativeId}
        {...(title !== undefined ? { title } : {})}
      />
    </div>
  );
};
