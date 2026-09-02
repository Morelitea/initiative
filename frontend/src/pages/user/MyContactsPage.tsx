import { useNavigate, useSearch } from "@tanstack/react-router";
import { Loader2, SearchX, Star, Users } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactSearchField } from "@/components/contacts/ContactSearchField";
import { ContactSection } from "@/components/contacts/ContactSection";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { StatusMessage } from "@/components/StatusMessage";
import { Accordion } from "@/components/ui/accordion";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  fetchContactPage,
  useContactSections,
  useFavoriteContacts,
  useToggleFavoriteContact,
} from "@/hooks/useContacts";
import { useViewPreference } from "@/hooks/useViewPreference";
import { getInitials } from "@/lib/initials";

const FAVORITES_VALUE = "favorites";
const COLLAPSE_SCOPE = "my-contacts-sections";

/** Pages pulled beyond a community's first, keyed by guild. */
type ExtraPages = Record<number, { items: ContactRead[]; pages: number; hasNext: boolean }>;

/** Which sections the reader has closed. Everything else is open. */
type CollapseState = { closed: string[] };
const DEFAULT_COLLAPSE: CollapseState = { closed: [] };

/**
 * My Contacts — the people you already share a community with, plus the ones
 * you starred.
 *
 * Favorites on top, then every community in the same order as the rail, each
 * a collapsible section listing its members alphabetically. Somebody in
 * several of your communities is listed under each of them; the chip on their
 * row points at the others.
 *
 * The sections arrive as one read, because the server can walk the reader's
 * communities in a single request the way every other "my" page does. The
 * starred list is a second read: a favorite may be somebody you share no
 * community with, so it cannot come from that walk.
 */
export const MyContactsPage = () => {
  const { t } = useTranslation(["contacts", "common"]);
  const navigate = useNavigate();
  const { q } = useSearch({ strict: false }) as { q?: string };
  const search = q ?? "";
  const searching = search.trim().length > 0;

  // Pages already pulled for a community beyond its first, so one section can
  // be read to the end without touching the others. Reset whenever the term
  // changes, because the sections underneath are a different set.
  const [extra, setExtra] = useState<ExtraPages>({});
  const [loadingMore, setLoadingMore] = useState<Set<number>>(new Set());
  const [loadedFor, setLoadedFor] = useState(search);
  if (loadedFor !== search) {
    setLoadedFor(search);
    setExtra({});
    setLoadingMore(new Set());
  }
  // Read by an in-flight load-more when it lands, to tell whether the term it
  // was asked under is still the one on screen.
  const searchRef = useRef(search);
  searchRef.current = search;

  const [collapse, setCollapse] = useViewPreference<CollapseState>(
    COLLAPSE_SCOPE,
    DEFAULT_COLLAPSE
  );

  const sectionsQuery = useContactSections(search);
  const favoritesQuery = useFavoriteContacts(search);

  const sections = useMemo(() => sectionsQuery.data?.sections ?? [], [sectionsQuery.data]);
  const favorites = useMemo(() => favoritesQuery.data?.items ?? [], [favoritesQuery.data]);

  const starredIds = useMemo(() => new Set(favorites.map((contact) => contact.id)), [favorites]);

  // Every id a chip can name is one of these sections, so the chip resolves
  // against what the page already has.
  const guilds = useMemo(() => {
    const map = new Map<number, ChipGuild>();
    for (const section of sections) {
      map.set(section.guild_id, {
        id: section.guild_id,
        name: section.guild_name,
        icon_url: section.icon_url,
      });
    }
    return map;
  }, [sections]);

  const setFavorite = useToggleFavoriteContact();

  const loadMore = useCallback(
    async (guildId: number, loadedPages: number) => {
      const askedFor = search;
      setLoadingMore((prev) => new Set(prev).add(guildId));
      try {
        const section = await fetchContactPage(guildId, loadedPages + 1, askedFor);
        // The term may have moved on while this was in flight. These rows are
        // the answer to a question nobody is asking now, and appending them
        // would put people who do not match under a section that is filtered.
        if (!section || searchRef.current !== askedFor) return;
        setExtra((prev) => {
          const held = prev[guildId];
          return {
            ...prev,
            [guildId]: {
              items: [...(held?.items ?? []), ...section.items],
              pages: loadedPages + 1,
              hasNext: section.has_next,
            },
          };
        });
      } finally {
        setLoadingMore((prev) => {
          const next = new Set(prev);
          next.delete(guildId);
          return next;
        });
      }
    },
    [search]
  );

  const toggleFavorite = useCallback(
    (contact: ContactRead) => setFavorite(contact.id, starredIds.has(contact.id)),
    [starredIds, setFavorite]
  );

  // While a term is set every matching section is open, and the reader's own
  // collapse state is left untouched so clearing the field restores it.
  const openValues = useMemo(() => {
    const all = [FAVORITES_VALUE, ...sections.map((s) => `guild-${s.guild_id}`)];
    if (searching) return all;
    const closed = new Set(collapse.closed);
    return all.filter((value) => !closed.has(value));
  }, [sections, searching, collapse.closed]);

  const onOpenChange = useCallback(
    (next: string[]) => {
      if (searching) return;
      const all = [FAVORITES_VALUE, ...sections.map((s) => `guild-${s.guild_id}`)];
      const open = new Set(next);
      setCollapse({ closed: all.filter((value) => !open.has(value)) });
    },
    [searching, sections, setCollapse]
  );

  if (sectionsQuery.isLoading || favoritesQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const nothingAtAll = sections.length === 0 && favorites.length === 0;

  return (
    <div className="space-y-4">
      <h1 className="font-semibold text-2xl">{t("title")}</h1>

      <ContactSearchField
        value={search}
        onChange={(next) =>
          void navigate({
            to: ".",
            search: next.trim() ? { q: next } : {},
            replace: true,
          })
        }
      />

      {nothingAtAll ? (
        <StatusMessage
          icon={searching ? <SearchX /> : <Users />}
          title={searching ? t("noMatches.title") : t("empty.title")}
          description={searching ? t("noMatches.description") : t("empty.description")}
        />
      ) : (
        <Accordion type="multiple" value={openValues} onValueChange={onOpenChange}>
          <ContactSection
            value={FAVORITES_VALUE}
            title={
              <>
                <Star className="size-4 text-amber-500" />
                <span>{t("favorites")}</span>
              </>
            }
            count={favoritesQuery.data?.total_count ?? 0}
            items={favorites}
            starredIds={starredIds}
            onToggleFavorite={toggleFavorite}
            guilds={guilds}
            emptyLabel={searching ? t("noMatches.section") : t("empty.favorites")}
          />

          {sections.map((section) => {
            const held = extra[section.guild_id];
            const items = held ? [...section.items, ...held.items] : section.items;
            const loadedPages = held?.pages ?? 1;
            const hasNext = held ? held.hasNext : section.has_next;
            return (
              <ContactSection
                key={section.guild_id}
                value={`guild-${section.guild_id}`}
                title={
                  <>
                    <Avatar className="size-5 rounded-md">
                      {section.icon_url ? <AvatarImage src={section.icon_url} alt="" /> : null}
                      <AvatarFallback className="rounded-md bg-muted text-[0.6rem] text-muted-foreground">
                        {getInitials(section.guild_name, "G")}
                      </AvatarFallback>
                    </Avatar>
                    <span className="min-w-0 truncate">{section.guild_name}</span>
                  </>
                }
                count={section.total_count}
                items={items}
                starredIds={starredIds}
                onToggleFavorite={toggleFavorite}
                omitGuildId={section.guild_id}
                guilds={guilds}
                emptyLabel={searching ? t("noMatches.section") : t("empty.guild")}
                onLoadMore={
                  hasNext ? () => void loadMore(section.guild_id, loadedPages) : undefined
                }
                isLoadingMore={loadingMore.has(section.guild_id)}
              />
            );
          })}
        </Accordion>
      )}
    </div>
  );
};
