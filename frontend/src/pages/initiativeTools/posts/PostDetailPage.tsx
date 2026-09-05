import { Link, useBlocker, useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { Loader2, Pin, PinOff, SearchX, Settings, ShieldAlert } from "lucide-react";
import { lazy, Suspense, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { StatusMessage } from "@/components/StatusMessage";
import { TagBadge } from "@/components/tags/TagBadge";
import { ToolBreadcrumb } from "@/components/tools/ToolBreadcrumb";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useInitiativeAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import { usePost, useSetPostPin, useUpdatePost } from "@/hooks/usePosts";
import { useRecordRecentView } from "@/hooks/useRecents";
import { toast } from "@/lib/chesterToast";
import { getHttpStatus } from "@/lib/errorMessage";
import { useGuildPath } from "@/lib/guildUrl";
import { hasWriteAccess } from "@/lib/permissions";
import { MAX_POST_TEXT_CHARS } from "@/lib/posts";
import { toolListRoute, toolSettingsRoute } from "@/lib/tools";

const Editor = lazy(() =>
  import("@/components/documents/editor/editor").then((m) => ({ default: m.Editor }))
);

/**
 * One notice, on its own page — where its comments and reactions live.
 *
 * The body is the same editor the board renders, switched to editable for
 * anyone with write access on the post. Pinning sits beside it but answers to
 * a different rule: initiative management, not write access, so an author can
 * edit their own notice without being able to lift it above everyone else's.
 */
export function PostDetailPage() {
  const { t } = useTranslation(["posts", "common"]);
  const { guildId, postId } = useParams({ strict: false }) as {
    guildId: string;
    postId: string;
  };
  const parsedId = Number(postId);
  const gp = useGuildPath();

  const postQuery = usePost(Number.isFinite(parsedId) ? parsedId : null);
  const post = postQuery.data;
  const initiativeId = useCanonicalInitiativeId(post?.initiative_id);

  const recordViewMutation = useRecordRecentView("post", Number(guildId));
  const viewedPostId = post?.id;
  useEffect(() => {
    if (!viewedPostId) return;
    recordViewMutation.mutate(viewedPostId);
  }, [viewedPostId, recordViewMutation.mutate]);

  const canEdit = hasWriteAccess(post?.my_permission_level);

  const initiativeQuery = useInitiative(post?.initiative_id ?? null);
  const { canManage } = useInitiativeAccess();
  const canPin = initiativeQuery.data ? canManage(initiativeQuery.data) : false;

  const update = useUpdatePost(parsedId, {
    onSuccess: () => {
      // Saved is no longer dirty — otherwise the guard goes on asking about an
      // edit that is already on the server.
      setDraft(null);
      toast.success(t("detailsUpdated"));
    },
  });
  const setPin = useSetPostPin(parsedId, {
    onSuccess: (updated) =>
      toast.success(updated.is_pinned ? t("pin.pinnedToast") : t("pin.unpinnedToast")),
  });

  // The editor is uncontrolled once mounted, so the draft lives here and is
  // saved explicitly — a notice is not a collaborative document, and nobody
  // wants a half-written correction broadcast as they type it.
  const [draft, setDraft] = useState<SerializedEditorState | null>(null);
  const isDirty = canEdit && draft !== null;

  // A body full of links, mentions and smart chips is a body full of things
  // that navigate — and an explicit Save means a click on one would otherwise
  // take the unsaved edit with it. Ask first.
  const blocker = useBlocker({ shouldBlockFn: () => isDirty, withResolver: true });

  // The same question for a reload or a closed tab, which the router never
  // sees.
  useEffect(() => {
    if (!isDirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("notFound")}</p>;
  }

  if (postQuery.isError) {
    const status = getHttpStatus(postQuery.error);
    const backTo = gp(toolListRoute(Tool.post, initiativeId));
    const backLabel = t("backToPosts");

    if (status === 403) {
      return (
        <StatusMessage
          icon={<ShieldAlert />}
          title={t("noAccess")}
          description={t("noAccessDescription")}
          backTo={backTo}
          backLabel={backLabel}
        />
      );
    }
    return (
      <StatusMessage
        icon={<SearchX />}
        title={t("notFound")}
        description={t("notFoundDescription")}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <ToolBreadcrumb
        tool={Tool.post}
        initiativeId={post?.initiative_id}
        trail={[{ label: post ? post.name : <Skeleton className="h-4 w-32" /> }]}
      />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          {post ? (
            <h1 className="font-semibold text-3xl tracking-tight">{post.name}</h1>
          ) : (
            <Skeleton className="h-9 w-64" />
          )}
          {post?.is_pinned && (
            <p className="flex items-center gap-1.5 text-primary text-xs">
              <Pin className="h-3.5 w-3.5" aria-hidden />
              {post.pin_expires_at
                ? t("pin.pinnedUntil", {
                    date: new Date(post.pin_expires_at).toLocaleDateString(),
                  })
                : t("pin.pinnedBanner")}
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {post && canPin && (
            <Button
              variant="outline"
              size="sm"
              disabled={setPin.isPending}
              onClick={() => setPin.mutate({ pinned: !post.is_pinned })}
              className="inline-flex items-center gap-2"
            >
              {post.is_pinned ? (
                <PinOff className="h-4 w-4" aria-hidden />
              ) : (
                <Pin className="h-4 w-4" aria-hidden />
              )}
              {post.is_pinned ? t("pin.unpin") : t("pin.pin")}
            </Button>
          )}
          {post && canEdit && (
            <Button variant="outline" size="sm" asChild>
              <Link
                to={gp(toolSettingsRoute(Tool.post, initiativeId, post.id))}
                className="inline-flex items-center gap-2"
              >
                <Settings className="h-4 w-4" aria-hidden />
                {t("common:toolSettings.title")}
              </Link>
            </Button>
          )}
        </div>
      </div>

      {post ? (
        <div className="space-y-3">
          <Suspense fallback={<Skeleton className="h-40 w-full" />}>
            <Editor
              key={post.id}
              editorSerializedState={post.body as unknown as SerializedEditorState}
              onSerializedChange={setDraft}
              readOnly={!canEdit}
              showToolbar={canEdit}
              initiativeId={post.initiative_id}
              supportsEntityMentions
              variant="post"
              maxLength={MAX_POST_TEXT_CHARS}
              // A post's editor draws no frame of its own. Reading it, that is
              // right — the notice is the page. Writing it, the bounds of what
              // you are editing have to be visible, so the page asks for them.
              className={canEdit ? "rounded-lg border bg-background" : undefined}
            />
          </Suspense>
          {canEdit && draft !== null && (
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={update.isPending}
                onClick={() => update.mutate({ body: draft as unknown as Record<string, unknown> })}
              >
                {update.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                {update.isPending ? t("saving") : t("common:save")}
              </Button>
            </div>
          )}
          {post.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {post.tags.map((tag) => (
                <TagBadge key={tag.id} tag={tag} size="sm" to={gp(`/tags/${tag.id}`)} />
              ))}
            </div>
          )}
        </div>
      ) : (
        <Skeleton className="h-40 w-full" />
      )}

      {post != null && <ToolCommentsPanel tool={Tool.post} entity={post} canModerate={canEdit} />}

      <ConfirmDialog
        open={blocker.status === "blocked"}
        onOpenChange={(open) => {
          if (!open) blocker.reset?.();
        }}
        title={t("unsaved.title")}
        description={t("unsaved.body")}
        confirmLabel={t("unsaved.leave")}
        cancelLabel={t("unsaved.stay")}
        onConfirm={() => blocker.proceed?.()}
        destructive
      />
    </div>
  );
}
