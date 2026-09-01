/**
 * Guild-wide search results.
 *
 * Three tabs and no counts on any of them: a tab is a place to look, not a
 * reported quantity. The split is by KIND of thing rather than one tab per
 * tool — per-tool tabs would privilege projects and documents and would reflow
 * every time a tool is added.
 *
 * Each tab is a differently scoped query, not a filter over one. `All` runs the
 * per-category queries side by side and shows a bounded few of each, so no
 * category can crowd the others out — and those same two answers are what let a
 * tab with nothing behind it render disabled instead of vanishing.
 */

import { useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2, Search, SearchX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
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
  isSearchTab,
  SEARCH_CATEGORIES,
  type SearchCategory,
  type SearchTab,
} from "@/lib/searchResults";

/** A page of one category. */
const PAGE_SIZE = 20;
/** How many of a category the All tab shows before pointing at its tab. */
const SECTION_LIMIT = 5;

export function SearchPage() {
  const { t } = useTranslation(["search", "common"]);
  const navigate = useNavigate();
  const { activeGuild } = useGuilds();
  const search = useSearch({ strict: false }) as { q?: string; tab?: string; page?: number };

  const query = (search.q ?? "").trim();
  const tab: SearchTab = isSearchTab(search.tab) ? search.tab : "all";
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
        tab: next === "all" ? undefined : next,
        page: undefined,
      }),
    });
  };

  const setPage = (next: number) => {
    void navigate({
      to: ".",
      search: (prev: Record<string, unknown>) => ({ ...prev, page: next > 1 ? next : undefined }),
    });
  };

  const enabled = query.length > 0;
  const tools = useGuildSearch(
    { q: query, types: categoryEntityTypes("tool"), limit: SECTION_LIMIT },
    { enabled }
  );
  const tags = useGuildSearch(
    { q: query, types: categoryEntityTypes("tag"), limit: SECTION_LIMIT },
    { enabled }
  );
  const sections: Record<SearchCategory, ReturnType<typeof useGuildSearch>> = {
    tool: tools,
    tag: tags,
  };

  // The open tab's own page. `all` reads the two above instead.
  const paged = useGuildSearch(
    {
      q: query,
      types: tab === "all" ? undefined : categoryEntityTypes(tab),
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    },
    { enabled: enabled && tab !== "all" }
  );

  const anyLoading = tools.isLoading || tags.isLoading || paged.isLoading;

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <h1 className="font-semibold text-3xl tracking-tight">{t("search:title")}</h1>
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
            <TabsTrigger value="all">{t("search:tabs.all")}</TabsTrigger>
            {SEARCH_CATEGORIES.map((category) => (
              <TabsTrigger
                key={category}
                value={category}
                // Nothing behind it, and not where the reader already is.
                disabled={
                  tab !== category &&
                  sections[category].isFetched &&
                  (sections[category].data?.total ?? 0) === 0
                }
              >
                {t(`search:tabs.${category}`)}
              </TabsTrigger>
            ))}
          </TabsBar>

          <TabsContent value="all" className="space-y-6">
            {anyLoading ? (
              <Loading />
            ) : SEARCH_CATEGORIES.every((c) => (sections[c].data?.items.length ?? 0) === 0) ? (
              <NoResults query={query} />
            ) : (
              SEARCH_CATEGORIES.map((category) => {
                const results = sections[category].data;
                if (!results || results.items.length === 0) return null;
                return (
                  <section key={category} className="space-y-1">
                    <div className="flex items-center justify-between px-3">
                      <h2 className="font-medium text-muted-foreground text-sm">
                        {t(`search:tabs.${category}`)}
                      </h2>
                      {results.total > results.items.length && (
                        <Button variant="link" size="sm" onClick={() => setTab(category)}>
                          {t("search:seeAll")}
                        </Button>
                      )}
                    </div>
                    {results.items.map((hit) => (
                      <SearchResultRow key={`${hit.entity_type}-${hit.entity_id}`} hit={hit} />
                    ))}
                  </section>
                );
              })
            )}
          </TabsContent>

          {SEARCH_CATEGORIES.map((category) => (
            <TabsContent key={category} value={category} className="space-y-1">
              {paged.isLoading ? (
                <Loading />
              ) : (paged.data?.items.length ?? 0) === 0 ? (
                <NoResults query={query} />
              ) : (
                <>
                  {paged.data?.items.map((hit) => (
                    <SearchResultRow key={`${hit.entity_type}-${hit.entity_id}`} hit={hit} />
                  ))}
                  <Pager results={paged.data} page={page} onPageChange={setPage} />
                </>
              )}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
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
