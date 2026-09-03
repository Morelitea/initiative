import { HelpCircle, MessageSquarePlus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommentCreate, CommentRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreateReferencedThingDialog } from "@/components/references/CreateReferencedThingDialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useAuth } from "@/hooks/useAuth";
import { useCreateComment, useDeleteComment, useUpdateComment } from "@/hooks/useComments";
import { useGuilds } from "@/hooks/useGuilds";
import { getErrorMessage } from "@/lib/errorMessage";
import { entityMentionSyntax } from "@/lib/mentions";
import { getUserDisplayName } from "@/lib/userDisplay";

import { CommentInput } from "./CommentInput";
import { CommentReferences } from "./CommentReferences";
import { CommentThread } from "./CommentThread";

export interface CommentWithReplies extends CommentRead {
  replies: CommentWithReplies[];
}

/** What a comment thread hangs off: any tool entity, plus tasks (a project's
 *  child, not a tool of its own). */
export type CommentEntity = "task" | Tool;

interface CommentSectionProps {
  entityType: CommentEntity;
  entityId: number;
  comments?: CommentRead[];
  onCommentCreated?: (comment: CommentRead) => void;
  onCommentDeleted?: (commentId: number) => void;
  onCommentUpdated?: (comment: CommentRead) => void;
  title?: string;
  isLoading?: boolean;
  canModerate?: boolean;
  initiativeId: number;
}

// Build comment tree from flat list
function buildCommentTree(comments: CommentRead[]): CommentWithReplies[] {
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
  const { t } = useTranslation("comments");
  const { activeGuildReadOnly } = useGuilds();
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const { user } = useAuth();

  const createComment = useCreateComment({
    onSuccess: (comment) => {
      setContent("");
      setError(null);
      onCommentCreated?.(comment);
    },
    onError: (err) => {
      setError(getErrorMessage(err, "documents:comments.errorCreate"));
    },
  });

  const deleteComment = useDeleteComment({
    onSuccess: (_data, commentId) => {
      setDeleteError(null);
      onCommentDeleted?.(commentId);
    },
    onError: (err) => {
      setDeleteError(getErrorMessage(err, "documents:comments.errorDelete"));
    },
  });

  const updateComment = useUpdateComment({
    onSuccess: (comment) => {
      setEditError(null);
      onCommentUpdated?.(comment);
    },
    onError: (err) => {
      setEditError(getErrorMessage(err, "documents:comments.errorUpdate"));
    },
  });

  // Build comment tree
  const commentTree = useMemo(() => buildCommentTree(comments), [comments]);
  const hasComments = comments.length > 0;
  // A name `[[ ]]` could not find. Holding it here opens the dialog that makes
  // it, which knows which tools this initiative has and which the writer may
  // add — neither of which a text box should be deciding.
  const [pendingCreate, setPendingCreate] = useState<string | null>(null);

  // Build display name maps from comment authors
  const userDisplayNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const comment of comments) {
      if (comment.author) {
        const displayName = getUserDisplayName(comment.author);
        map.set(comment.author.id, displayName);
      }
    }
    return map;
  }, [comments]);

  // Each entity kind carries its id under its own `<entity>_id` field, and a
  // comment names exactly one.
  const buildPayload = (commentBody: string, parentCommentId?: number): CommentCreate => {
    const payload: CommentCreate = {
      content: commentBody,
    };
    payload[`${entityType}_id`] = entityId;
    if (parentCommentId) {
      payload.parent_comment_id = parentCommentId;
    }
    return payload;
  };

  const handleSubmit = (commentContent: string) => {
    const normalized = commentContent.trim();
    if (!normalized) {
      setError(t("contentRequired"));
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
      await updateComment.mutateAsync({ commentId, data: { content: normalized } });
      return true;
    } catch {
      return false;
    }
  };

  return (
    // Full width wherever it lands: a comment thread is a conversation, and a
    // narrow column makes every reply wrap. Callers give it its own row rather
    // than a sidebar or a half-width cell.
    <CommentReferences contents={comments.map((comment) => comment.content)}>
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MessageSquarePlus className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h3>{title ?? t("title")}</h3>
            </div>
            <HoverCard>
              <HoverCardTrigger asChild>
                <button type="button" className="text-muted-foreground hover:text-foreground">
                  <HelpCircle className="h-4 w-4" />
                </button>
              </HoverCardTrigger>
              <HoverCardContent side="left" align="start" className="w-56">
                <p className="font-medium text-sm">{t("mentionSyntax")}</p>
                <ul className="mt-2 space-y-1.5 text-sm">
                  <li>
                    <code className="rounded bg-muted px-1 text-xs">@</code> {t("mentionUser")}
                  </li>
                  <li>
                    <code className="rounded bg-muted px-1 text-xs">#</code> {t("mentionAnything")}
                  </li>
                  <li className="text-muted-foreground">{t("mentionNarrow")}</li>
                </ul>
                <p className="mt-3 font-medium text-sm">{t("formattingSyntax")}</p>
                <p className="mt-1 text-muted-foreground text-sm">{t("markdownHint")}</p>
              </HoverCardContent>
            </HoverCard>
          </CardTitle>
        </CardHeader>

        <CardContent>
          {activeGuildReadOnly ? (
            <p className="text-muted-foreground text-sm">{t("readOnlyNote")}</p>
          ) : (
            <CommentInput
              onCreateRequest={setPendingCreate}
              value={content}
              onChange={setContent}
              onSubmit={handleSubmit}
              isSubmitting={createComment.isPending}
              initiativeId={initiativeId}
              error={error}
              onClearError={() => setError(null)}
            />
          )}

          {/* One request for everything the whole thread points at: forty
            comments naming the same task ask about it once. */}
          <div className="mt-4 space-y-3">
            {isLoading ? (
              <p className="text-muted-foreground text-sm">{t("loading")}</p>
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
                  canReact={!activeGuildReadOnly}
                  deleteError={deleteComment.variables === comment.id ? deleteError : null}
                  userDisplayNames={userDisplayNames}
                />
              ))
            ) : (
              <p className="text-muted-foreground text-sm">{t("empty")}</p>
            )}
            {deleteError && !deleteComment.variables && (
              <p className="text-destructive text-sm">{deleteError}</p>
            )}
            {editError && <p className="text-destructive text-sm">{editError}</p>}
          </div>
        </CardContent>
      </Card>
      {pendingCreate !== null && (
        <CreateReferencedThingDialog
          name={pendingCreate}
          initiativeId={initiativeId}
          onCreated={(made) => {
            // Straight into the sentence being written, so making something
            // never costs the writer their place.
            setContent(
              (current) =>
                `${current}${entityMentionSyntax(made.entityType, made.name, made.entityId)} `
            );
            setPendingCreate(null);
          }}
          onClose={() => setPendingCreate(null)}
        />
      )}
    </CommentReferences>
  );
};
