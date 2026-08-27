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

  const heading = (
    <div className="space-y-1">
      <h1 className="font-semibold text-3xl tracking-tight">{t("guilds:community.title")}</h1>
      <p className="text-muted-foreground text-sm">{t("guilds:community.subtitle")}</p>
    </div>
  );

  // No directory on this deployment: no search box, no shelves, and no request.
  if (!configLoading && directoryOff) {
    return (
      <div className="space-y-6">
        {heading}
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
      {heading}

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
