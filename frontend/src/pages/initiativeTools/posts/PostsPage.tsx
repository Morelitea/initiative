import { useRouter } from "@tanstack/react-router";
import { Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreatePostDialog } from "@/components/initiativeTools/posts/CreatePostDialog";
import { PostCard } from "@/components/initiativeTools/posts/PostCard";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useInitiativeAccess, useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import { usePostsList } from "@/hooks/usePosts";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

type PostsViewProps = {
  /** The initiative whose board this is. Required: a board belongs to one. */
  fixedInitiativeId: number;
  canCreate?: boolean;
};

/**
 * An initiative's bulletin board.
 *
 * A feed rather than a grid of cards, because a notice is meant to be read
 * where it sits. The server owns the order — live pins first, then newest —
 * and pages in twenties, so this walks pages instead of scrolling one long
 * list: each row carries a body the editor has to mount.
 */
export const PostsView = ({ fixedInitiativeId, canCreate }: PostsViewProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  const postsQuery = usePostsList({
    initiative_id: fixedInitiativeId,
    page,
    // Left to the server's own default so the cap lives in one place.
    ...(search.trim() ? { search: search.trim() } : {}),
  });

  const { canCreate: canCreateDerived } = useToolCreateAccess(Tool.post, {
    initiativeId: fixedInitiativeId,
  });
  const canCreatePosts = canCreate ?? canCreateDerived;

  // Pinning is initiative authority, not write access on the post — the same
  // rule the server applies, asked here only to decide what to offer.
  const initiativeQuery = useInitiative(fixedInitiativeId);
  const { canManage } = useInitiativeAccess();
  const canPin = initiativeQuery.data ? canManage(initiativeQuery.data) : false;

  const {
    open: createOpen,
    setOpen: setCreateOpen,
    onOpenChange: handleCreateOpenChange,
  } = useCreateFromSearchParam();

  useRegisterPrimaryCreateAction(
    canCreatePosts ? { run: () => setCreateOpen(true), label: t("createPost") } : null
  );

  const posts = postsQuery.data?.items ?? [];
  const totalCount = postsQuery.data?.total_count ?? 0;
  const hasNext = postsQuery.data?.has_next ?? false;

  return (
    <div className="space-y-6">
      <ToolListToolbar
        actions={
          canCreatePosts ? (
            <Button variant="outline" size="sm" className="h-9" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("createPost")}
            </Button>
          ) : null
        }
      />

      <Input
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setPage(1);
        }}
        placeholder={t("filters.searchPosts")}
        aria-label={t("filters.filterByName")}
        className="max-w-sm"
      />

      {postsQuery.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("loading")}
        </div>
      ) : postsQuery.isError ? (
        <p className="text-destructive text-sm">{t("loadError")}</p>
      ) : posts.length > 0 ? (
        <>
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
            {posts.map((post) => (
              <PostCard key={post.id} post={post} canPin={canPin} />
            ))}
          </div>
          {(hasNext || page > 1) && (
            <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 1 || postsQuery.isFetching}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("common:previous")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasNext || postsQuery.isFetching}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("loadMore")}
              </Button>
            </div>
          )}
        </>
      ) : totalCount > 0 || search.trim() ? (
        <p className="text-muted-foreground text-sm">{t("filters.noMatchingPosts")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("noPosts")}</CardTitle>
            <CardDescription>{t("noPostsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setCreateOpen(true)} disabled={!canCreatePosts}>
              {t("createFirst")}
            </Button>
          </CardContent>
        </Card>
      )}

      <CreatePostDialog
        open={createOpen}
        onOpenChange={handleCreateOpenChange}
        initiativeId={fixedInitiativeId}
        onSuccess={(post) => {
          void router.navigate({
            to: gp(toolDetailRoute(Tool.post, fixedInitiativeId, post.id)),
          });
        }}
      />
    </div>
  );
};
