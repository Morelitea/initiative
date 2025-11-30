import { FormEvent, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { isAxiosError } from "axios";
import { MessageSquarePlus, Trash2 } from "lucide-react";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useAuth } from "@/hooks/useAuth";
import type { Comment } from "@/types/api";

type CommentEntity = "task" | "document";

interface CommentSectionProps {
  entityType: CommentEntity;
  entityId: number;
  parentCommentId?: number;
  comments?: Comment[];
  onCommentCreated?: (comment: Comment) => void;
  onCommentDeleted?: (commentId: number) => void;
  title?: string;
  isLoading?: boolean;
  canModerate?: boolean;
}

interface CommentPayload {
  content: string;
  task_id?: number;
  document_id?: number;
  parent_comment_id?: number;
}

export const CommentSection = ({
  entityType,
  entityId,
  parentCommentId,
  comments = [],
  onCommentCreated,
  onCommentDeleted,
  title = "Comments",
  isLoading = false,
  canModerate = false,
}: CommentSectionProps) => {
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { user } = useAuth();

  const createComment = useMutation({
    mutationFn: async (payload: CommentPayload) => {
      const response = await apiClient.post<Comment>("/comments/", payload);
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
      setError("Unable to post comment right now.");
    },
  });

  const deleteComment = useMutation({
    mutationFn: async (commentId: number) => {
      await apiClient.delete(`/comments/${commentId}`);
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
      setDeleteError("Unable to delete comment right now.");
    },
  });

  const hasComments = useMemo(() => comments.length > 0, [comments]);

  const getDisplayName = (comment: Comment) =>
    comment.author?.full_name?.trim() || comment.author?.email || `User #${comment.author_id}`;

  const getAvatarSrc = (comment: Comment) =>
    comment.author?.avatar_url || comment.author?.avatar_base64 || undefined;

  const getInitials = (value: string) => {
    if (!value) {
      return "?";
    }
    const parts = value.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) {
      return value.charAt(0).toUpperCase();
    }
    const initials = parts
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join("");
    return initials || value.charAt(0).toUpperCase();
  };

  const buildPayload = (commentBody: string): CommentPayload => {
    const payload: CommentPayload = {
      content: commentBody,
      parent_comment_id: parentCommentId,
    };
    if (entityType === "task") {
      payload.task_id = entityId;
    } else {
      payload.document_id = entityId;
    }
    if (!parentCommentId) {
      delete payload.parent_comment_id;
    }
    return payload;
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = content.trim();
    if (!normalized) {
      setError("Content is required.");
      return;
    }
    createComment.mutate(buildPayload(normalized));
  };

  const isSubmitting = createComment.isPending;

  return (
    <section className="border-border bg-card space-y-4 rounded-lg border p-4">
      <div className="flex items-center gap-2">
        <MessageSquarePlus className="text-muted-foreground h-4 w-4" aria-hidden="true" />
        <h3 className="text-muted-foreground text-sm font-semibold tracking-wide uppercase">
          {title}
        </h3>
      </div>

      <form onSubmit={handleSubmit} className="space-y-2">
        <Textarea
          value={content}
          onChange={(event) => {
            setContent(event.target.value);
            if (error) {
              setError(null);
            }
          }}
          placeholder="Share feedback or ask a question..."
          rows={4}
          disabled={isSubmitting}
        />
        {error && <p className="text-destructive text-sm">{error}</p>}
        <div className="flex justify-end">
          <Button type="submit" disabled={isSubmitting || content.trim().length === 0}>
            {isSubmitting ? "Posting..." : "Post Comment"}
          </Button>
        </div>
      </form>

      <div className="space-y-3">
        {isLoading ? (
          <p className="text-muted-foreground text-sm">Loading comments…</p>
        ) : hasComments ? (
          <ul className="space-y-3">
            {comments.map((comment) => {
              const displayName = getDisplayName(comment);
              const avatarSrc = getAvatarSrc(comment);
              const initials = getInitials(displayName);
              const canDelete = user?.id === comment.author_id || canModerate;
              const isDeleting = deleteComment.isPending && deleteComment.variables === comment.id;

              return (
                <li key={comment.id} className="border-border rounded-md border p-3">
                  <div className="flex gap-3">
                    <Avatar className="bg-background h-9 w-9 border">
                      {avatarSrc ? <AvatarImage src={avatarSrc} alt={displayName} /> : null}
                      <AvatarFallback>{initials}</AvatarFallback>
                    </Avatar>
                    <div className="flex-1">
                      <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 text-xs">
                        <span className="text-foreground font-medium">{displayName}</span>
                        <div className="flex items-center gap-2">
                          <span>
                            {formatDistanceToNow(new Date(comment.created_at), {
                              addSuffix: true,
                            })}
                          </span>
                          {canDelete ? (
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive h-8 px-2 text-xs"
                              disabled={isDeleting}
                              onClick={() => deleteComment.mutate(comment.id)}
                            >
                              {isDeleting ? (
                                "Deleting…"
                              ) : (
                                <Trash2 className="mr-1 h-3.5 w-3.5" aria-hidden="true" />
                              )}
                            </Button>
                          ) : null}
                        </div>
                      </div>
                      <p className="text-foreground mt-2 text-sm whitespace-pre-wrap">
                        {comment.content}
                      </p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">
            No comments yet. Be the first to contribute.
          </p>
        )}
        {deleteError && <p className="text-destructive text-sm">{deleteError}</p>}
      </div>
    </section>
  );
};
