import { useNavigate, useSearch } from "@tanstack/react-router";
import { SearchX, Users } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactColumnHeader, ContactRowsSkeleton } from "@/components/contacts/ContactColumns";
import { ContactSearchField } from "@/components/contacts/ContactSearchField";
import { ContactSearchProgress } from "@/components/contacts/ContactSearchProgress";
import {
  FAVORITES_VALUE,
  FavoriteContactsSection,
} from "@/components/contacts/FavoriteContactsSection";
import { GuildContactSection } from "@/components/contacts/GuildContactSection";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import { StatusMessage } from "@/components/StatusMessage";
import { Accordion } from "@/components/ui/accordion";
import {
  useContactSections,
  useFavoriteContacts,
  useToggleFavoriteContact,
} from "@/hooks/useContacts";
import { useViewPreference } from "@/hooks/useViewPreference";
import { cn } from "@/lib/utils";

const COLLAPSE_SCOPE = "my-contacts-sections";

/** Which sections the reader has closed. Everything else is open. */
type CollapseState = { closed: string[] };
const DEFAULT_COLLAPSE: CollapseState = { closed: [] };

/**
 * My Contacts — the people you already share a community with, plus the ones
 * you starred.
 *
 * One table, read down: Favorites on top, then every community in the same
 * order as the rail, each a collapsible group of the same columns. Somebody in
 * several of your communities is listed under each of them, on the same
 * vertical lines, and the last column points at the others.
 *
 * The sections arrive as one read, because the server can walk the reader's
 * communities in a single request the way every other "my" page does. The
 * starred list is a second read: a favorite may be somebody you share no
 * community with, so it cannot come from that walk. Paging a single community
 * is a third, made by that section for itself.
 */
export const MyContactsPage = () => {
  const { t } = useTranslation(["contacts", "common"]);
  const navigate = useNavigate();
  const { q } = useSearch({ strict: false }) as { q?: string };
  const search = q ?? "";
  const searching = search.trim().length > 0;

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

  const isFirstLoad = sectionsQuery.isLoading || favoritesQuery.isLoading;
  // A term in flight, whether or not last term's answer is still on screen.
  const isSearchPending =
    searching && (isFirstLoad || sectionsQuery.isFetching || favoritesQuery.isFetching);
  const nothingAtAll = sections.length === 0 && favorites.length === 0;

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="font-semibold text-2xl">{t("title")}</h1>
        <p className="max-w-prose text-muted-foreground text-sm">{t("subtitle")}</p>
      </header>

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

      {isSearchPending ? <ContactSearchProgress /> : null}

      {isFirstLoad ? (
        <div className="rounded-lg border px-3 py-2">
          <span className="sr-only" role="status">
            {t("loading")}
          </span>
          <ContactColumnHeader />
          <div className="pt-2">
            <ContactRowsSkeleton count={8} />
          </div>
        </div>
      ) : nothingAtAll ? (
        <StatusMessage
          icon={searching ? <SearchX /> : <Users />}
          title={searching ? t("noMatches.title") : t("empty.title")}
          description={searching ? t("noMatches.description") : t("empty.description")}
        />
      ) : (
        <div
          className={cn(
            "rounded-lg border px-3 py-2 transition-opacity",
            isSearchPending && "opacity-60"
          )}
        >
          <ContactColumnHeader />
          <Accordion type="multiple" value={openValues} onValueChange={onOpenChange}>
            {/* Remounted on a new term: under a different term every section is
                a different set of people, so none of them keeps its page. */}
            <FavoriteContactsSection
              key={`favorites:${search}`}
              items={favorites}
              starredIds={starredIds}
              onToggleFavorite={toggleFavorite}
              guilds={guilds}
              searching={searching}
            />
            {sections.map((section) => (
              <GuildContactSection
                key={`${section.guild_id}:${search}`}
                section={section}
                search={search}
                starredIds={starredIds}
                onToggleFavorite={toggleFavorite}
                guilds={guilds}
              />
            ))}
          </Accordion>
        </div>
      )}
    </div>
  );
};
