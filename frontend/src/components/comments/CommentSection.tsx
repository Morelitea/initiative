import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { useTranslation } from "react-i18next";
import { HelpCircle, MessageSquarePlus } from "lucide-react";

import {
  createCommentApiV1CommentsPost,
  updateCommentApiV1CommentsCommentIdPatch,
  deleteCommentApiV1CommentsCommentIdDelete,
} from "@/api/generated/comments/comments";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useAuth } from "@/hooks/useAuth";
import { CommentInput } from "./CommentInput";
import { CommentThread } from "./CommentThread";
import type { Comment, CommentWithReplies } from "@/types/api";

type CommentEntity = "task" | "document";

interface CommentSectionProps {
  entityType: CommentEntity;
  entityId: number;
  comments?: Comment[];
  onCommentCreated?: (comment: Comment) => void;
  onCommentDeleted?: (commentId: number) => void;
  onCommentUpdated?: (comment: Comment) => void;
  title?: string;
  isLoading?: boolean;
  canModerate?: boolean;
  initiativeId: number;
}

interface CommentPayload {
  content: string;
  task_id?: number;
  document_id?: number;
  parent_comment_id?: number;
}

interface CommentUpdatePayload {
  content: string;
}

// Build comment tree from flat list
function buildCommentTree(comments: Comment[]): CommentWithReplies[] {
  const map = new Map<number, CommentWithReplies>();
  const roots: CommentWithReplies[] = [];

  // First pass: create all nodes
  for (const comment of comments) {
    map.set(comment.id, { ...comment, replies: [] });
  }

  // Second pass: link children to parents
  for (const comment of comments) {
    const node = map.get(comment.id)!;
    if (comment.parent_comment_id && map.has(comment.parent_comment_id)) {
      map.get(comment.parent_comment_id)!.replies.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

export const CommentSection = ({
  entityType,
  entityId,
  comments = [],
  onCommentCreated,
  onCommentDeleted,
  onCommentUpdated,
  title,
  isLoading = false,
  canModerate = false,
  initiativeId,
}: CommentSectionProps) => {
  const { t } = useTranslation("documents");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const { user } = useAuth();

  const createComment = useMutation({
    mutationFn: async (payload: CommentPayload) => {
      const response = await (createCommentApiV1CommentsPost(payload) as unknown as Promise<{
        data: Comment;
      }>);
      return response.data;
    },
    onSuccess: (comment) => {
      setContent("");
      setError(null);
      onCommentCreated?.(comment);
    },
    onError: (err) => {
      if (isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        if (typeof detail === "string" && detail.trim()) {
          setError(detail);
          return;
        }
      }
      setError(t("comments.errorCreate"));
    },
  });

  const deleteComment = useMutation({
    mutationFn: async (commentId: number) => {
      await deleteCommentApiV1CommentsCommentIdDelete(commentId);
      return commentId;
    },
    onSuccess: (commentId) => {
      setDeleteError(null);
      onCommentDeleted?.(commentId);
    },
    onError: (err) => {
      if (isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        if (typeof detail === "string" && detail.trim()) {
          setDeleteError(detail);
          return;
        }
      }
      setDeleteError(t("comments.errorDelete"));
    },
  });

  const updateComment = useMutation({
    mutationFn: async ({
      commentId,
      payload,
    }: {
      commentId: number;
      payload: CommentUpdatePayload;
    }) => {
      const response = await (updateCommentApiV1CommentsCommentIdPatch(
        commentId,
        payload
      ) as unknown as Promise<{ data: Comment }>);
      return response.data;
    },
    onSuccess: (comment) => {
      setEditError(null);
      onCommentUpdated?.(comment);
    },
    onError: (err) => {
      if (isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        if (typeof detail === "string" && detail.trim()) {
          setEditError(detail);
          return;
        }
      }
      setEditError(t("comments.errorUpdate"));
    },
  });

  // Build comment tree
  const commentTree = useMemo(() => buildCommentTree(comments), [comments]);
  const hasComments = comments.length > 0;

  // Build display name maps from comment authors
  const userDisplayNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const comment of comments) {
      if (comment.author) {
        const displayName = comment.author.full_name?.trim() || comment.author.email;
        map.set(comment.author.id, displayName);
      }
    }
    return map;
  }, [comments]);

  const buildPayload = (commentBody: string, parentCommentId?: number): CommentPayload => {
    const payload: CommentPayload = {
      content: commentBody,
    };
    if (entityType === "task") {
      payload.task_id = entityId;
    } else {
      payload.document_id = entityId;
    }
    if (parentCommentId) {
      payload.parent_comment_id = parentCommentId;
    }
    return payload;
  };

  const handleSubmit = (commentContent: string) => {
    const normalized = commentContent.trim();
    if (!normalized) {
      setError(t("comments.contentRequired"));
      return;
    }
    createComment.mutate(buildPayload(normalized));
  };

  const handleReply = (parentId: number, replyContent: string) => {
    const normalized = replyContent.trim();
    if (!normalized) return;
    createComment.mutate(buildPayload(normalized, parentId));
  };

  const handleDelete = (commentId: number) => {
    deleteComment.mutate(commentId);
  };

  const handleEdit = async (commentId: number, editedContent: string): Promise<boolean> => {
    const normalized = editedContent.trim();
    if (!normalized) return false;
    try {
      await updateComment.mutateAsync({ commentId, payload: { content: normalized } });
      return true;
    } catch {
      return false;
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquarePlus className="text-muted-foreground h-4 w-4" aria-hidden="true" />
            <h3>{title ?? t("comments.title")}</h3>
          </div>
          <HoverCard>
            <HoverCardTrigger asChild>
              <button type="button" className="text-muted-foreground hover:text-foreground">
                <HelpCircle className="h-4 w-4" />
              </button>
            </HoverCardTrigger>
            <HoverCardContent side="left" align="start" className="w-56">
              <p className="text-sm font-medium">{t("comments.mentionSyntax")}</p>
              <ul className="mt-2 space-y-1.5 text-sm">
                <li>
                  <code className="bg-muted rounded px-1 text-xs">@</code>{" "}
                  {t("comments.mentionUser")}
                </li>
                <li>
                  {/* eslint-disable-next-line i18next/no-literal-string */}
                  <code className="bg-muted rounded px-1 text-xs">#task:</code>{" "}
                  {t("comments.mentionTask")}
                </li>
                <li>
                  {/* eslint-disable-next-line i18next/no-literal-string */}
                  <code className="bg-muted rounded px-1 text-xs">#doc:</code>{" "}
                  {t("comments.mentionDoc")}
                </li>
                <li>
                  {/* eslint-disable-next-line i18next/no-literal-string */}
                  <code className="bg-muted rounded px-1 text-xs">#project:</code>{" "}
                  {t("comments.mentionProject")}
                </li>
              </ul>
            </HoverCardContent>
          </HoverCard>
        </CardTitle>
      </CardHeader>

      <CardContent>
        <CommentInput
          value={content}
          onChange={setContent}
          onSubmit={handleSubmit}
          isSubmitting={createComment.isPending}
          initiativeId={initiativeId}
          error={error}
          onClearError={() => setError(null)}
        />

        <div className="mt-4 space-y-3">
          {isLoading ? (
            <p className="text-muted-foreground text-sm">{t("comments.loading")}</p>
          ) : hasComments ? (
            commentTree.map((comment) => (
              <CommentThread
                key={comment.id}
                comment={comment}
                depth={0}
                onReply={handleReply}
                onDelete={handleDelete}
                onEdit={handleEdit}
                canModerate={canModerate}
                currentUserId={user?.id}
                initiativeId={initiativeId}
                isSubmitting={
                  createComment.isPending || deleteComment.isPending || updateComment.isPending
                }
                deleteError={deleteComment.variables === comment.id ? deleteError : null}
                userDisplayNames={userDisplayNames}
              />
            ))
          ) : (
            <p className="text-muted-foreground text-sm">{t("comments.empty")}</p>
          )}
          {deleteError && !deleteComment.variables && (
            <p className="text-destructive text-sm">{deleteError}</p>
          )}
          {editError && <p className="text-destructive text-sm">{editError}</p>}
        </div>
      </CardContent>
    </Card>
  );
};
