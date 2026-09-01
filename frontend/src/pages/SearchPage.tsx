/**
 * Guild-wide search results.
 *
 * Tabs by KIND of thing rather than one per tool, and no counts on any of
 * them: a tab is a place to look, not a reported quantity. Per-tool tabs would
 * privilege projects and documents — an artifact of them being the two core
 * tools — and would reflow every time a tool is added.
 *
 * A tab is a differently scoped query, not a filter over one, so the tab a
 * reader is on is the only scope that runs. The others are asked for a single
 * row, which is enough to show a tab with nothing behind it as disabled rather
 * than let the reader click through to an empty page.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2, Search, SearchX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SearchResults } from "@/api/generated/initiativeAPI.schemas";
import { StatusMessage } from "@/components/StatusMessage";
import { SearchResultRow } from "@/components/search/SearchResultRow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuilds } from "@/hooks/useGuilds";
import { useGuildSearch } from "@/hooks/useSearch";
import {
  categoryEntityTypes,
  DEFAULT_SEARCH_CATEGORY,
  isSearchCategory,
  SEARCH_CATEGORIES,
  type SearchCategory,
} from "@/lib/searchResults";

/** A page of one category. */
const PAGE_SIZE = 20;

export function SearchPage() {
  const { t } = useTranslation(["search", "common"]);
  const navigate = useNavigate();
  const { activeGuild } = useGuilds();
  const search = useSearch({ strict: false }) as { q?: string; tab?: string; page?: number };

  const query = (search.q ?? "").trim();
  const tab: SearchCategory = isSearchCategory(search.tab) ? search.tab : DEFAULT_SEARCH_CATEGORY;
  const page = search.page && search.page >= 1 ? search.page : 1;

  // The URL is the query's home — a result page has to be linkable. The input
  // is local so typing stays responsive, and the two are reconciled through the
  // last value committed: without that, a commit landing mid-word would put the
  // older query back in the box.
  const [input, setInput] = useState(search.q ?? "");
  const committed = useRef(query);
  const debounced = useDebouncedValue(input.trim(), 250);

  useEffect(() => {
    if (query === committed.current) return;
    committed.current = query;
    setInput(query);
  }, [query]);

  useEffect(() => {
    if (debounced === committed.current) return;
    committed.current = debounced;
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        q: debounced || undefined,
        page: undefined,
      }),
      replace: true,
    });
  }, [debounced, navigate]);

  const setTab = (next: string) => {
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => ({
        ...prev,
        tab: next === DEFAULT_SEARCH_CATEGORY ? undefined : next,
        page: undefined,
      }),
    });
  };

  const setPage = useCallback(
    (next: number, replace = false) => {
      void navigate({
        to: ".",
        search: (prev: Record<string, unknown>) => ({ ...prev, page: next > 1 ? next : undefined }),
        replace,
      });
    },
    [navigate]
  );

  const enabled = query.length > 0;
  const results = useGuildSearch(
    {
      q: query,
      types: categoryEntityTypes(tab),
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    },
    { enabled }
  );

  // A page past the end of the answer — a link from before the content moved,
  // or a query that has since narrowed. Left alone it reads as "nothing
  // matched", which is the opposite of what happened, so it corrects itself
  // back onto the last page that has results.
  const total = settledTotal(results);
  const lastPage = total === undefined ? undefined : Math.max(1, Math.ceil(total / PAGE_SIZE));
  const outOfRange = lastPage !== undefined && page > lastPage;
  useEffect(() => {
    if (!outOfRange || lastPage === undefined) return;
    setPage(lastPage, true);
  }, [outOfRange, lastPage, setPage]);

  const items = results.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <h1 className="font-semibold text-3xl tracking-tight">
          {activeGuild
            ? t("search:titleInGuild", { guildName: activeGuild.name })
            : t("search:title")}
        </h1>
        <div className="relative max-w-2xl">
          <Search className="absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            className="pl-9"
            autoFocus
            aria-label={t("search:title")}
            placeholder={t("search:placeholder", {
              guildName: activeGuild?.name ?? t("common:appName"),
            })}
          />
        </div>
      </div>

      {!enabled ? (
        <StatusMessage
          icon={<Search />}
          title={t("search:prompt.title")}
          description={t("search:prompt.description")}
        />
      ) : (
        <Tabs value={tab} onValueChange={setTab} className="space-y-4">
          <TabsBar>
            {SEARCH_CATEGORIES.map((category) => (
              // Every tab stays open, including one holding nothing: closing
              // it off leaves the reader unable to confirm that for themselves,
              // and unable to get back once a changed query fills it. An empty
              // tab says so.
              <TabsTrigger key={category} value={category}>
                {t(`search:tabs.${category}`)}
              </TabsTrigger>
            ))}
          </TabsBar>

          {SEARCH_CATEGORIES.map((category) => (
            <TabsContent key={category} value={category} className="space-y-1">
              {results.isLoading || outOfRange ? (
                <Loading />
              ) : items.length === 0 ? (
                <NoResults query={query} />
              ) : (
                <>
                  {items.map((hit) => (
                    <SearchResultRow key={`${hit.entity_type}-${hit.entity_id}`} hit={hit} />
                  ))}
                  <Pager results={results.data} page={page} onPageChange={setPage} />
                </>
              )}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}

/**
 * How many things this query matched, or `undefined` while that isn't known
 * yet.
 *
 * The previous query's results stay on screen while a new one is in flight, so
 * that a reader typing isn't left staring at an empty page. Their total belongs
 * to the query that is leaving: it says nothing about how many pages the
 * arriving one has, or whether its tab holds anything. Anything drawing a
 * conclusion from a total reads it through here.
 */
function settledTotal(query: ReturnType<typeof useGuildSearch>): number | undefined {
  if (query.isPlaceholderData || !query.isFetched) return undefined;
  return query.data?.total;
}

function Loading() {
  return (
    <div className="flex h-40 items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}

function NoResults({ query }: { query: string }) {
  const { t } = useTranslation("search");
  return (
    <StatusMessage
      icon={<SearchX />}
      title={t("empty.title", { query })}
      description={t("empty.description")}
    />
  );
}

function Pager({
  results,
  page,
  onPageChange,
}: {
  results?: SearchResults;
  page: number;
  onPageChange: (page: number) => void;
}) {
  const { t } = useTranslation("common");
  if (!results) return null;
  const hasNext = results.offset + results.items.length < results.total;
  if (page === 1 && !hasNext) return null;
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        {t("previous")}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={!hasNext}
        onClick={() => onPageChange(page + 1)}
      >
        {t("next")}
      </Button>
    </div>
  );
}
