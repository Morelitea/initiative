import { useRouter } from "@tanstack/react-router";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Loader2, Plus } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CreatePostDialog } from "@/components/initiativeTools/posts/CreatePostDialog";
import { PostCard } from "@/components/initiativeTools/posts/PostCard";
import { PostsFilterBar, type ReadFilter } from "@/components/initiativeTools/posts/PostsFilterBar";
import { ToolListToolbar } from "@/components/initiativeTools/shared/ToolListToolbar";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateFromSearchParam } from "@/hooks/useCreateFromSearchParam";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useInitiativeAccess, useToolCreateAccess } from "@/hooks/useInitiativeAccess";
import { useInitiative } from "@/hooks/useInitiatives";
import { PostReadTrackerProvider } from "@/hooks/usePostReadTracker";
import { usePostsFeed } from "@/hooks/usePosts";
import { useGuildPath } from "@/lib/guildUrl";
import { toolDetailRoute } from "@/lib/tools";

/**
 * A first guess at a card's height, corrected by measurement as each mounts.
 *
 * Only the notices near the window are ever mounted, which is the whole point:
 * every card mounts a Lexical editor for its body, and an hour of scrolling
 * should not leave a hundred of them alive.
 *
 * Deliberately not a threshold. Turning virtualization on partway down a list
 * swaps every rendered card for an estimated one mid-scroll, and the browser
 * keeps the scroll offset while the content under it changes height — which
 * lands the reader somewhere else entirely, usually the top. Virtualizing from
 * the first render costs nothing on a short board (everything fits in the
 * window and overscan, so everything is rendered) and there is no moment where
 * the page changes shape underneath somebody.
 */
const CARD_ESTIMATE_HEIGHT = 420;

/**
 * Cards kept mounted either side of the window.
 *
 * Higher than a list of cheap rows would want, because mounting a card is
 * mounting an editor: the cost is paid when a card enters the set, and paying
 * it during the scroll is what a dropped frame looks like. Three gives it a
 * screen of warning.
 */
const VIRTUALIZER_OVERSCAN = 3;

/** The gap between cards, applied INSIDE each measured element. A flex `gap`
 *  sits between items and so is invisible to `measureElement`, which leaves
 *  the virtualizer's model shorter than the real list by the gap times the
 *  number of rows — and everything below drifts. */
const CARD_GAP = "pb-4";

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
 * and hands over five at a time; the board fetches the next five as the reader
 * nears the bottom rather than making them ask for them.
 *
 * The list is virtualized from the first render, so what an hour of scrolling
 * costs is a couple of screens of editors rather than every editor the reader
 * has passed. Heights are measured rather than assumed: a notice is as tall as
 * what somebody wrote.
 */
export const PostsView = ({ fixedInitiativeId, canCreate }: PostsViewProps) => {
  const { t } = useTranslation(["posts", "common"]);
  const router = useRouter();
  const gp = useGuildPath();

  const [searchQuery, setSearchQuery] = useState("");
  const [readFilter, setReadFilter] = useState<ReadFilter>("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const search = useDebouncedValue(searchQuery, 300);

  const postsQuery = usePostsFeed({
    initiative_id: fixedInitiativeId,
    ...(search.trim() ? { search: search.trim() } : {}),
    ...(readFilter === "unread" ? { unread: true } : {}),
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

  const posts = useMemo(
    () => postsQuery.data?.pages.flatMap((page) => page.items) ?? [],
    [postsQuery.data]
  );
  const totalCount = postsQuery.data?.pages[0]?.total_count ?? 0;
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = postsQuery;

  const activeFilterCount = (search.trim() ? 1 : 0) + (readFilter === "unread" ? 1 : 0);
  const clearFilters = useCallback(() => {
    setSearchQuery("");
    setReadFilter("all");
  }, []);

  // The page itself scrolls, not a box inside it, so the virtualizer measures
  // against the app's scroller rather than a container of its own.
  const listRef = useRef<HTMLDivElement | null>(null);
  // Found once and held. The virtualizer asks for the scroller on every scroll
  // event, and a document-wide query per event is work done during exactly the
  // frames that must not be busy.
  const scrollerRef = useRef<HTMLElement | null>(null);
  const getScrollElement = useCallback(() => {
    scrollerRef.current ??= document.querySelector<HTMLElement>("[data-app-scroll]");
    return scrollerRef.current;
  }, []);

  // How far down the scrolled content the list starts — the toolbar and the
  // filter panel above it. Measured after layout rather than read during
  // render, where the ref is still null on the first pass and every offset
  // would be short by the height of everything above.
  const [listOffset, setListOffset] = useState(0);
  useLayoutEffect(() => {
    const list = listRef.current;
    const scroller = getScrollElement();
    if (!list || !scroller) return;
    setListOffset(
      list.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop
    );
    // The filter panel opens and closes above the list, which moves it.
  }, [getScrollElement, filtersOpen]);

  const virtualizer = useVirtualizer({
    count: posts.length,
    getScrollElement,
    estimateSize: () => CARD_ESTIMATE_HEIGHT,
    overscan: VIRTUALIZER_OVERSCAN,
    scrollMargin: listOffset,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const paddingTop = virtualItems.length > 0 ? virtualItems[0].start - listOffset : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
      : 0;

  // The bottom of the list asks for the next page as it comes into view.
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      // A screen of lead time, so the next five are there before the reader is.
      { rootMargin: "600px" }
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const renderCard = useCallback(
    (index: number) => <PostCard key={posts[index].id} post={posts[index]} canPin={canPin} />,
    [posts, canPin]
  );

  return (
    <PostReadTrackerProvider>
      <div className="space-y-6">
        <ToolListToolbar
          // The panel below holds the fields; this is what opens it. Without
          // it the filters exist and nothing on the page reaches them.
          filters={{
            open: filtersOpen,
            onOpenChange: setFiltersOpen,
            activeCount: activeFilterCount,
          }}
          actions={
            canCreatePosts ? (
              <Button
                variant="outline"
                size="sm"
                className="h-9"
                onClick={() => setCreateOpen(true)}
              >
                <Plus className="h-4 w-4" />
                {t("createPost")}
              </Button>
            ) : null
          }
        />

        <PostsFilterBar
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          readFilter={readFilter}
          onReadFilterChange={setReadFilter}
          filtersOpen={filtersOpen}
          onFiltersOpenChange={setFiltersOpen}
          onClear={clearFilters}
          activeCount={activeFilterCount}
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
            {/* No flex `gap` here: the spacing lives inside each measured
                element (see CARD_GAP), so what the virtualizer measures is
                what the list actually occupies. */}
            <div ref={listRef} className="mx-auto flex w-full max-w-3xl flex-col">
              <div style={{ height: paddingTop }} />
              {virtualItems.map((item) => (
                <div
                  key={posts[item.index].id}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  className={CARD_GAP}
                >
                  {renderCard(item.index)}
                </div>
              ))}
              <div style={{ height: paddingBottom }} />
            </div>
            <div ref={sentinelRef} className="h-px" aria-hidden />
            {isFetchingNextPage && (
              <div className="flex items-center justify-center gap-2 text-muted-foreground text-sm">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t("loading")}
              </div>
            )}
          </>
        ) : totalCount > 0 || activeFilterCount > 0 ? (
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
    </PostReadTrackerProvider>
  );
};
