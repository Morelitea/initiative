import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { useTranslation } from "react-i18next";
import { Pencil, Reply, Trash2 } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useDateLocale } from "@/hooks/useDateLocale";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { CommentContent } from "./CommentContent";
import { CommentInput } from "./CommentInput";
import type { CommentWithReplies } from "./CommentSection";

const MAX_VISUAL_DEPTH = 3;

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
  deleteError,
  userDisplayNames = new Map(),
  taskTitles = new Map(),
  docTitles = new Map(),
  projectNames = new Map(),
}: CommentThreadProps) => {
  const { t } = useTranslation(["documents", "common"]);
  const dateLocale = useDateLocale();
  const [isReplying, setIsReplying] = useState(false);
  const [replyContent, setReplyContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(comment.content);

  const displayName =
    comment.author?.full_name?.trim() || comment.author?.email || `User #${comment.author_id}`;
  const avatarSrc =
    resolveUploadUrl(comment.author?.avatar_url) || comment.author?.avatar_base64 || undefined;

  const getInitials = (value: string) => {
    if (!value) return "?";
    const parts = value.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return value.charAt(0).toUpperCase();
    const initials = parts
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("");
    return initials || value.charAt(0).toUpperCase();
  };

  const canDelete = currentUserId === comment.author_id || canModerate;
  const canEdit = currentUserId === comment.author_id;
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
    <div className={visualDepth > 0 ? "border-border ml-4 border-l pl-4" : ""}>
      <div className="border-border rounded-md border p-3">
        <div className="flex gap-3">
          <Avatar className="bg-background h-9 w-9 border">
            {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
            <AvatarFallback>{getInitials(displayName)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 flex-1">
            <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className="text-foreground font-medium">{displayName}</span>
              <span className="whitespace-nowrap">
                {formatDistanceToNow(new Date(comment.created_at), {
                  addSuffix: true,
                  locale: dateLocale,
                })}
                {isEdited && (
                  <span className="text-muted-foreground ml-1">{t("comments.edited")}</span>
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
                      className="text-destructive hover:text-destructive h-7 px-2 text-xs"
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
            <div className="text-foreground mt-2 text-sm">
              {isEditing ? (
                <div className="space-y-2">
                  <CommentInput
                    value={editContent}
                    onChange={setEditContent}
                    onSubmit={handleEditSubmit}
                    placeholder={t("comments.editPlaceholder")}
                    submitLabel={t("common:save")}
                    isSubmitting={isSubmitting}
                    initiativeId={initiativeId}
                    autoFocus
                    compact
                  />
                  <Button type="button" variant="ghost" size="sm" onClick={handleEditCancel}>
                    {t("common:cancel")}
                  </Button>
                </div>
              ) : (
                <CommentContent content={comment.content} />
              )}
            </div>
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
            autoFocus
            compact
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="mt-1"
            onClick={() => {
              setIsReplying(false);
              setReplyContent("");
            }}
          >
            {t("common:cancel")}
          </Button>
        </div>
      )}

      {/* Delete error */}
      {deleteError && <p className="text-destructive mt-1 text-sm">{deleteError}</p>}

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
