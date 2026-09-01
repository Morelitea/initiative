import { Pencil, Reply, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ReactionTarget } from "@/api/generated/initiativeAPI.schemas";
import { ReactionBar } from "@/components/reactions/ReactionBar";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getInitialsForUser, getUserDisplayName, isAnonymizedUser } from "@/lib/userDisplay";

import { CommentContent } from "./CommentContent";
import { CommentInput } from "./CommentInput";
import type { CommentWithReplies } from "./CommentSection";

/**
 * Nesting is indented for three levels and then stops — past that the
 * conversation is better read as a flat run than as a staircase off the right
 * edge, especially on a phone.
 */
const MAX_VISUAL_DEPTH = 3;

/**
 * The thread line takes a different theme colour at each level, cycling
 * through the chart palette. Depth is the one thing a nested thread has to
 * convey and indentation alone stops conveying it once it is capped, so the
 * colour carries it the rest of the way — and it reads as the app's own
 * palette rather than as decoration bolted on.
 */
const THREAD_LINE_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const threadLineColor = (depth: number) =>
  THREAD_LINE_COLORS[(depth - 1) % THREAD_LINE_COLORS.length];

interface CommentThreadProps {
  comment: CommentWithReplies;
  depth: number;
  onReply: (parentId: number, content: string) => void;
  onDelete: (commentId: number) => void;
  onEdit: (commentId: number, content: string) => Promise<boolean>;
  canModerate: boolean;
  currentUserId?: number;
  initiativeId: number;
  isSubmitting?: boolean;
  /** False while the viewer may read the thread but not write to it. */
  canReact?: boolean;
  deleteError?: string | null;
  userDisplayNames?: Map<number, string>;
  taskTitles?: Map<number, string>;
  docTitles?: Map<number, string>;
  projectNames?: Map<number, string>;
}

export const CommentThread = ({
  comment,
  depth,
  onReply,
  onDelete,
  onEdit,
  canModerate,
  currentUserId,
  initiativeId,
  isSubmitting = false,
  canReact = true,
  deleteError,
  userDisplayNames = new Map(),
  taskTitles = new Map(),
  docTitles = new Map(),
  projectNames = new Map(),
}: CommentThreadProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const relativeCreatedAt = useRelativeTime(comment.created_at);
  const [isReplying, setIsReplying] = useState(false);
  const [replyContent, setReplyContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(comment.content);

  const anonymizedAuthor = isAnonymizedUser(comment.author);
  const displayName = comment.author
    ? getUserDisplayName(comment.author, `User #${comment.created_by}`)
    : `User #${comment.created_by}`;
  const avatarSrc = anonymizedAuthor
    ? undefined
    : resolveUploadUrl(comment.author?.avatar_url) || undefined;

  const canDelete = currentUserId === comment.created_by || canModerate;
  const canEdit = currentUserId === comment.created_by;
  const visualDepth = Math.min(depth, MAX_VISUAL_DEPTH);
  const isEdited = Boolean(comment.updated_at);

  const handleReplySubmit = (content: string) => {
    onReply(comment.id, content);
    setReplyContent("");
    setIsReplying(false);
  };

  const handleEditSubmit = async (content: string) => {
    const success = await onEdit(comment.id, content);
    if (success) {
      setIsEditing(false);
    }
  };

  const handleEditCancel = () => {
    setIsEditing(false);
    setEditContent(comment.content);
  };

  return (
    <div
      className={visualDepth > 0 ? "ml-4 border-l-2 pl-4" : ""}
      style={visualDepth > 0 ? { borderColor: threadLineColor(visualDepth) } : undefined}
    >
      <div className="rounded-md border border-border p-3">
        <div className="flex gap-3">
          <Avatar className="h-9 w-9 border bg-background">
            {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
            <AvatarFallback userId={anonymizedAuthor ? null : comment.created_by}>
              {getInitialsForUser(comment.author)}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
              <span className="font-medium text-foreground">{displayName}</span>
              <span className="whitespace-nowrap">
                {relativeCreatedAt}
                {isEdited && (
                  <span className="ml-1 text-muted-foreground">{t("comments.edited")}</span>
                )}
              </span>
              {!isEditing && (
                <div className="ml-auto flex items-center gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => setIsReplying(!isReplying)}
                  >
                    <Reply className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only sm:not-sr-only sm:ml-1">{t("comments.reply")}</span>
                  </Button>
                  {canEdit && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => setIsEditing(true)}
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="sr-only sm:not-sr-only sm:ml-1">{t("common:edit")}</span>
                    </Button>
                  )}
                  {canDelete && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-destructive text-xs hover:text-destructive"
                      disabled={isSubmitting}
                      onClick={() => onDelete(comment.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="sr-only">{t("comments.deleteComment")}</span>
                    </Button>
                  )}
                </div>
              )}
            </div>
            <div className="mt-2 text-foreground text-sm">
              {isEditing ? (
                <CommentInput
                  value={editContent}
                  onChange={setEditContent}
                  onSubmit={handleEditSubmit}
                  placeholder={t("comments.editPlaceholder")}
                  submitLabel={t("common:save")}
                  isSubmitting={isSubmitting}
                  initiativeId={initiativeId}
                  onCancel={handleEditCancel}
                  autoFocus
                  compact
                />
              ) : (
                <CommentContent content={comment.content} />
              )}
            </div>
            {!isEditing && (
              <ReactionBar
                className="mt-2"
                targetType={ReactionTarget.comment}
                targetId={comment.id}
                groups={comment.reactions}
                canReact={canReact}
              />
            )}
          </div>
        </div>
      </div>

      {/* Reply input */}
      {isReplying && (
        <div className="mt-2 ml-4">
          <CommentInput
            value={replyContent}
            onChange={setReplyContent}
            onSubmit={handleReplySubmit}
            placeholder={t("comments.replyPlaceholder")}
            submitLabel={t("comments.reply")}
            isSubmitting={isSubmitting}
            initiativeId={initiativeId}
            onCancel={() => {
              setIsReplying(false);
              setReplyContent("");
            }}
            autoFocus
            compact
          />
        </div>
      )}

      {/* Delete error */}
      {deleteError && <p className="mt-1 text-destructive text-sm">{deleteError}</p>}

      {/* Nested replies */}
      {comment.replies.length > 0 && (
        <div className="mt-3 space-y-3">
          {comment.replies.map((reply) => (
            <CommentThread
              key={reply.id}
              comment={reply}
              depth={depth + 1}
              onReply={onReply}
              onDelete={onDelete}
              onEdit={onEdit}
              canModerate={canModerate}
              currentUserId={currentUserId}
              initiativeId={initiativeId}
              isSubmitting={isSubmitting}
              canReact={canReact}
              deleteError={deleteError}
              userDisplayNames={userDisplayNames}
              taskTitles={taskTitles}
              docTitles={docTitles}
              projectNames={projectNames}
            />
          ))}
        </div>
      )}
    </div>
  );
};
