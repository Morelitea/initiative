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
import { useTranslation } from "react-i18next";

import { CommunityCard } from "@/components/guilds/CommunityCard";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useCommunityGuilds } from "@/hooks/useCommunities";
import { getErrorCode } from "@/lib/errorMessage";
import { asGuildCategory } from "@/lib/guildCategories";

/** Stable keys for the loading placeholders — an index key on a list that can
 *  change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function CommunitiesPage() {
  const { t } = useTranslation(["guilds", "common"]);
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

  // The page's title sits on the banner rather than above it. The banner is a
  // fixed light-toned image, so its words are held at a dark neutral instead of
  // the theme's foreground — the theme changes under them, the image does not.
  // It shortens with the viewport rather than keeping one ratio, so the two
  // lines have room to wrap on a phone without the image growing on a desktop.
  const hero = (
    <div className="relative overflow-hidden rounded-xl">
      <img
        src="/images/community-banner.webp"
        alt=""
        className="aspect-[2/1] max-h-72 w-full object-cover sm:aspect-[3/1] lg:aspect-[4/1]"
      />
      {/* The artwork is pale but busy, so the words sit on a wash of the same
          light rather than directly on the swirls behind them. */}
      <div className="absolute inset-0 bg-gradient-to-r from-white/85 via-white/50 to-transparent" />
      <div className="absolute inset-0 flex flex-col justify-center gap-1 px-6 sm:gap-2 sm:px-10">
        <h1 className="text-balance font-semibold text-2xl text-neutral-900 tracking-tight sm:text-3xl lg:text-4xl">
          {t("guilds:community.heroTitle")}
        </h1>
        <p className="max-w-xl text-neutral-800 text-sm lg:text-base">
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
