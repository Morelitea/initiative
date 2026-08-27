/**
 * The community directory, as a place you browse.
 *
 * A filter rail beside a card grid: search at the top, then the shelves a guild
 * can file itself under, starting with "All". The rail is the page's own — it
 * narrows results rather than navigating, so it stays next to what it filters
 * instead of joining the app's navigation sidebar. On a narrow screen it
 * becomes a row of chips above the grid.
 *
 * The directory is platform-level, so this asks nothing about the caller's
 * current guild. Whether they are already in one of these is answered by the
 * card payload itself.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { CloudOff, SearchX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { GuildCategory } from "@/api/generated/initiativeAPI.schemas";
import { CommunityCard } from "@/components/guilds/CommunityCard";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCommunityGuilds } from "@/hooks/useCommunities";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { asGuildCategory, GUILD_CATEGORIES, guildCategoryLabel } from "@/lib/guildCategories";
import { cn } from "@/lib/utils";

/** Stable keys for the loading placeholders — an index key on a list that can
 *  change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function CommunitiesPage() {
  const { t } = useTranslation(["guilds", "common"]);
  const navigate = useNavigate();
  // The category lives in the URL so a filtered directory can be linked and
  // survives a reload; the search box does not, because it changes per keystroke.
  //
  // Read loosely and re-narrowed here rather than trusted from the route:
  // `useSearch({ strict: false })` returns the params as they are and does not
  // run the route's `validateSearch`, so anywhere this page is mounted another
  // way an unrecognized value would otherwise filter the grid down to nothing.
  const rawSearch = useSearch({ strict: false }) as { category?: unknown };
  const category = asGuildCategory(rawSearch.category);
  const [query, setQuery] = useState("");
  const search = useDebouncedValue(query, 250);

  const directory = useCommunityGuilds({
    q: search.trim() || undefined,
    category: category ?? undefined,
  });

  const selectCategory = (next: GuildCategory | undefined) => {
    void navigate({
      to: "/communities",
      search: next ? { category: next } : {},
      replace: true,
    });
  };

  // The grid is a shelf that grows, so the loaded pages are shown as one list.
  const guilds = directory.data?.pages.flatMap((page) => page.items) ?? [];
  // How many matched, not how many are on screen — every page carries the
  // same figure, so the first one answers it.
  const total = directory.data?.pages[0]?.total ?? 0;

  const categoryButton = (value: GuildCategory | undefined, label: string) => {
    const selected = category === value || (!category && !value);
    return (
      <button
        key={value ?? "all"}
        type="button"
        onClick={() => selectCategory(value)}
        aria-pressed={selected}
        className={cn(
          "shrink-0 rounded-lg px-3 py-2 text-left text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:w-full",
          selected
            ? "bg-primary/10 font-medium text-primary"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"
        )}
      >
        {label}
      </button>
    );
  };

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("guilds:community.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("guilds:community.subtitle")}</p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <aside className="lg:sticky lg:top-20 lg:w-56 lg:shrink-0">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("guilds:community.searchPlaceholder")}
            aria-label={t("guilds:community.searchPlaceholder")}
          />
          <nav aria-label={t("guilds:community.categoriesHeading")} className="mt-4">
            <h2 className="px-3 pb-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
              {t("guilds:community.categoriesHeading")}
            </h2>
            {/* A scrolling row on narrow screens, a list beside the grid on wide ones. */}
            <div className="scrollbar-thin flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
              {categoryButton(undefined, t("guilds:community.allCategories"))}
              {GUILD_CATEGORIES.map((value) => categoryButton(value, guildCategoryLabel(value, t)))}
            </div>
          </nav>
        </aside>

        <div className="min-w-0 flex-1 space-y-4">
          {directory.isError ? (
            // A directory that failed to answer is not a directory with nothing
            // in it, and saying so would send someone looking for guilds that exist.
            <StatusMessage
              icon={<CloudOff />}
              title={t("guilds:community.unavailableTitle")}
              description={t("guilds:community.unavailableDescription")}
            />
          ) : directory.isLoading ? (
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
              title={
                search ? t("guilds:community.noResultsTitle") : t("guilds:community.emptyTitle")
              }
              description={
                search
                  ? t("guilds:community.noResultsDescription", { query: search })
                  : t("guilds:community.emptyDescription")
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
