/**
 * The community directory, as a place you browse.
 *
 * The cards, and only the cards. What narrows them — the search box and the
 * shelves a guild can file itself under — is the app's sidebar while this page
 * is open (``CommunityDirectorySidebar``), which is where every other place in
 * the app keeps what it is browsed by. The two agree through the URL: the
 * sidebar writes ``q`` and ``category``, this reads them, and a filtered
 * directory is therefore a link.
 *
 * The directory is platform-level, so this asks nothing about the caller's
 * current guild. Whether they are already in one of these is answered by the
 * card payload itself.
 *
 * Whether there is a directory at all is the platform owner's setting. Where it
 * is off the page still exists — it can be linked to, and a link should say
 * what happened — but it says so instead of searching. A client that had not
 * heard yet asks and is refused, which lands in the same place: the server's
 * answer is what settles it, not the config this page loaded with.
 */

import { useSearch } from "@tanstack/react-router";
import { CloudOff, SearchX } from "lucide-react";
import { type CSSProperties, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityCard } from "@/components/guilds/CommunityCard";
import { CommunitySearchField } from "@/components/guilds/CommunitySearchField";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunityGuilds } from "@/hooks/useCommunities";
import { getErrorCode } from "@/lib/errorMessage";
import { asGuildCategory } from "@/lib/guildCategories";

/**
 * Widens an element from the padded, centred column a page is rendered in to
 * the whole content area beside the sidebar.
 *
 * How wide that area is depends on the shell around the page — which sidebars
 * are open, and which of the two shells the directory is being shown in — so it
 * is measured rather than restated as classes here, and measured again when it
 * changes. Until it has been, the classes on the element still take it out to
 * the edges of the column's padding, so nothing jumps.
 */
const useFullBleed = <T extends HTMLElement>() => {
  const ref = useRef<T>(null);
  const [style, setStyle] = useState<CSSProperties>();

  useLayoutEffect(() => {
    const element = ref.current;
    const column = element?.parentElement;
    const area = element?.closest("main")?.parentElement;
    if (!column || !area) return;

    const measure = () => {
      const columnBox = column.getBoundingClientRect();
      const areaBox = area.getBoundingClientRect();
      // Set from the column rather than from the element, whose own box is
      // what these values move.
      setStyle((current) =>
        current?.width === areaBox.width && current?.marginLeft === areaBox.left - columnBox.left
          ? current
          : {
              marginLeft: areaBox.left - columnBox.left,
              marginRight: 0,
              width: areaBox.width,
              maxWidth: "none",
            }
      );
    };
    measure();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(area);
    observer.observe(column);
    return () => observer.disconnect();
  }, []);

  return { ref, style };
};

/** Stable keys for the loading placeholders — an index key on a list that can
 *  change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function CommunitiesPage() {
  const { t } = useTranslation(["guilds", "common"]);
  const banner = useFullBleed<HTMLDivElement>();
  // Read loosely and re-narrowed here rather than trusted from the route:
  // `useSearch({ strict: false })` returns the params as they are and does not
  // run the route's `validateSearch`, so anywhere this page is mounted another
  // way an unrecognized value would otherwise filter the grid down to nothing.
  const rawSearch = useSearch({ strict: false }) as { category?: unknown; q?: unknown };
  const category = asGuildCategory(rawSearch.category);
  const search = typeof rawSearch.q === "string" ? rawSearch.q : "";

  const { communityDirectoryEnabled, isLoading: configLoading } = useAppConfig();

  const directory = useCommunityGuilds(
    {
      q: search.trim() || undefined,
      category: category ?? undefined,
    },
    { enabled: communityDirectoryEnabled }
  );

  // The grid is a shelf that grows, so the loaded pages are shown as one list.
  const guilds = directory.data?.pages.flatMap((page) => page.items) ?? [];
  // How many matched, not how many are on screen — every page carries the
  // same figure, so the first one answers it.
  const total = directory.data?.pages[0]?.total ?? 0;

  // Either this client was told there is no directory, or it asked and was told
  // so. The second is how a tab that was open when an owner switched it off
  // finds out — a refusal is an answer, not the momentary failure the
  // unavailable message describes.
  const directoryOff =
    !communityDirectoryEnabled || getErrorCode(directory.error) === "COMMUNITY_DIRECTORY_DISABLED";

  // The page's title sits centred on the banner rather than above it. The banner is a
  // fixed light-toned image, so its words are held at a dark neutral instead of
  // the theme's foreground — the theme changes under them, the image does not,
  // and they carry a halo of the artwork's own light so the detail behind them
  // stays visible.
  //
  // It runs the full width of the content area rather than of the page: the
  // shell renders a page in a padded, centred column, and the banner is widened
  // back out to everything beside the sidebar. Its lower edge fades out in the
  // artwork itself, so what it fades into is the page.
  //
  // From `lg` up the image is in flow, sharing a grid cell with the copy, so
  // the banner is as tall as whichever needs more room — the image at its own
  // proportions, with the copy centred on it, and a translation that wraps to
  // more lines opens the banner up rather than running past it.
  //
  // Below that the image would be a 4:1 strip too short to hold a heading, so
  // it is taken out of flow to fill a banner the copy sizes instead, over a
  // minimum that keeps a phone's close to square rather than a strip. There it
  // is matched to the banner's height and centred, so its width overhangs and
  // is clipped: what shows is the middle of the artwork at something like its
  // own size, all of it top to bottom, so the fade along the bottom is still
  // the edge. Both are positioned, so the copy paints over the image rather
  // than under it.
  const hero = (
    <div
      ref={banner.ref}
      style={banner.style}
      className="relative -mx-4 -mt-4 grid overflow-hidden md:-mx-8 md:-mt-8"
    >
      <img
        src="/images/community-banner.webp"
        alt=""
        className="absolute inset-y-0 left-1/2 col-start-1 row-start-1 h-full w-auto max-w-none -translate-x-1/2 lg:static lg:h-auto lg:w-full lg:max-w-full lg:translate-x-0 lg:self-start"
      />
      <div className="relative col-start-1 row-start-1 flex min-h-[85vw] flex-col items-center justify-center gap-1 px-4 py-10 text-center sm:min-h-[45vw] sm:gap-2 md:min-h-[28vw] md:px-8 lg:min-h-0">
        <h1 className="text-balance font-black text-4xl text-neutral-900 tracking-tight [text-shadow:0_0_10px_rgba(255,255,255,0.95),0_0_28px_rgba(255,255,255,0.8)] sm:text-5xl lg:text-6xl">
          {t("guilds:community.heroTitle")}
        </h1>
        <p className="max-w-2xl text-balance font-medium text-base text-neutral-800 [text-shadow:0_0_8px_rgba(255,255,255,0.95),0_0_20px_rgba(255,255,255,0.8)] sm:text-lg lg:text-xl">
          {t("guilds:community.heroSubtitle")}
        </p>
      </div>
    </div>
  );

  // No directory on this deployment: no search box, no shelves, and no request.
  if (!configLoading && directoryOff) {
    return (
      <div className="space-y-6">
        {hero}
        <StatusMessage
          icon={<CloudOff />}
          title={t("guilds:community.disabledTitle")}
          description={t("guilds:community.disabledDescription")}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {hero}

      {/* Below `lg` the sidebar this normally sits in is off-canvas, so the
          page carries the search rather than making someone open a drawer to
          reach it. The shelves stay in the sidebar: they are a list of twelve,
          and the search is the one that answers "is my thing here at all". */}
      <CommunitySearchField className="lg:hidden" />

      {directory.isError ? (
        // A directory that failed to answer is not a directory with nothing
        // in it, and saying so would send someone looking for guilds that exist.
        <StatusMessage
          icon={<CloudOff />}
          title={t("guilds:community.unavailableTitle")}
          description={t("guilds:community.unavailableDescription")}
        />
      ) : configLoading || directory.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-52 w-full rounded-xl" />
          ))}
        </div>
      ) : guilds.length ? (
        <>
          <p className="text-muted-foreground text-sm">
            {t("guilds:community.resultCount", { count: total })}
          </p>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {guilds.map((guild) => (
              <CommunityCard key={guild.id} guild={guild} />
            ))}
          </div>
          {directory.hasNextPage ? (
            <div className="flex justify-center pt-2">
              <Button
                variant="outline"
                onClick={() => void directory.fetchNextPage()}
                disabled={directory.isFetchingNextPage}
              >
                {t("guilds:community.showMore")}
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <StatusMessage
          icon={<SearchX />}
          title={search ? t("guilds:community.noResultsTitle") : t("guilds:community.emptyTitle")}
          description={
            search
              ? t("guilds:community.noResultsDescription", { query: search })
              : t("guilds:community.emptyDescription")
          }
        />
      )}
    </div>
  );
}
