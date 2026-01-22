import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { HelpCircle, MessageSquarePlus } from "lucide-react";

import { apiClient } from "@/api/client";
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
  title = "Comments",
  isLoading = false,
  canModerate = false,
  initiativeId,
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
      setError("Content is required.");
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquarePlus className="text-muted-foreground h-4 w-4" aria-hidden="true" />
            <h3>{title}</h3>
          </div>
          <HoverCard>
            <HoverCardTrigger asChild>
              <button type="button" className="text-muted-foreground hover:text-foreground">
                <HelpCircle className="h-4 w-4" />
              </button>
            </HoverCardTrigger>
            <HoverCardContent side="left" align="start" className="w-56">
              <p className="text-sm font-medium">Mention syntax</p>
              <ul className="mt-2 space-y-1.5 text-sm">
                <li>
                  <code className="bg-muted rounded px-1 text-xs">@</code> mention a user
                </li>
                <li>
                  <code className="bg-muted rounded px-1 text-xs">#task:</code> link a task
                </li>
                <li>
                  <code className="bg-muted rounded px-1 text-xs">#doc:</code> link a document
                </li>
                <li>
                  <code className="bg-muted rounded px-1 text-xs">#project:</code> link a project
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
            <p className="text-muted-foreground text-sm">Loading comments...</p>
          ) : hasComments ? (
            commentTree.map((comment) => (
              <CommentThread
                key={comment.id}
                comment={comment}
                depth={0}
                onReply={handleReply}
                onDelete={handleDelete}
                canModerate={canModerate}
                currentUserId={user?.id}
                initiativeId={initiativeId}
                isSubmitting={createComment.isPending || deleteComment.isPending}
                deleteError={deleteComment.variables === comment.id ? deleteError : null}
                userDisplayNames={userDisplayNames}
              />
            ))
          ) : (
            <p className="text-muted-foreground text-sm">
              No comments yet. Be the first to contribute.
            </p>
          )}
          {deleteError && !deleteComment.variables && (
            <p className="text-destructive text-sm">{deleteError}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
};
