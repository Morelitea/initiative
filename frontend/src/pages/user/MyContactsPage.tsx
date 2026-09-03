import { useNavigate, useSearch } from "@tanstack/react-router";
import { Link2, MessageSquare, SearchX, Users } from "lucide-react";
import { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { ContactRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactColumnHeader, ContactRowsSkeleton } from "@/components/contacts/ContactColumns";
import { ContactRequestsSection } from "@/components/contacts/ContactRequestsSection";
import { ContactSearchField } from "@/components/contacts/ContactSearchField";
import { ContactSearchProgress } from "@/components/contacts/ContactSearchProgress";
import {
  FAVORITES_VALUE,
  FavoriteContactsSection,
} from "@/components/contacts/FavoriteContactsSection";
import { GrantContactSection } from "@/components/contacts/GrantContactSection";
import { GuildContactSection } from "@/components/contacts/GuildContactSection";
import type { ChipGuild } from "@/components/contacts/SharedGuildChip";
import {
  AgeUnansweredPanel,
  PrivatePanel,
  unreachableReason,
} from "@/components/contacts/UnreachableEmptyState";
import { StatusMessage } from "@/components/StatusMessage";
import { Accordion } from "@/components/ui/accordion";
import {
  useContactSections,
  useFavoriteContacts,
  useToggleFavoriteContact,
} from "@/hooks/useContacts";
import { useConnections, useDmSettings, useMessageRequests } from "@/hooks/useDirectMessages";
import { useViewPreference } from "@/hooks/useViewPreference";
import { cn } from "@/lib/utils";

const COLLAPSE_SCOPE = "my-contacts-sections";
const CONNECTIONS_VALUE = "connections";
const OPEN_CHANNELS_VALUE = "open-channels";

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
  const dmQuery = useDmSettings();
  const connectionsQuery = useConnections();
  const messagesQuery = useMessageRequests();
  const favoritesQuery = useFavoriteContacts(search);

  const sections = useMemo(() => sectionsQuery.data?.sections ?? [], [sectionsQuery.data]);
  const favorites = useMemo(() => favoritesQuery.data?.items ?? [], [favoritesQuery.data]);

  const starredIds = useMemo(() => new Set(favorites.map((contact) => contact.id)), [favorites]);

  // Neither list is narrowed by the server — both arrive whole — so the term
  // is applied here, on the handle, which is all these rows carry.
  const matches = useCallback(
    (grant: { username: string; discriminator: number }) => {
      const term = search.trim().toLowerCase();
      if (!term) return true;
      const handle = `${grant.username}#${String(grant.discriminator).padStart(4, "0")}`;
      return handle.includes(term.replace(/^@/, ""));
    },
    [search]
  );

  // Only the count, to decide whether the strip appears at all — the section
  // itself reads the same two queries and renders them.
  const pendingRequests =
    (connectionsQuery.data?.incoming?.length ?? 0) +
    (connectionsQuery.data?.outgoing?.length ?? 0) +
    (messagesQuery.data?.incoming?.length ?? 0) +
    (messagesQuery.data?.outgoing?.length ?? 0);

  const connections = useMemo(
    () => (connectionsQuery.data?.accepted ?? []).filter(matches),
    [connectionsQuery.data, matches]
  );

  // Accepting a connection opens the channel with it, so every connection also
  // holds a message grant. Listing those again here would make this section a
  // near-copy of the one above it; what is left is the people this section
  // exists for — the ones an agreement to message is the *only* thing the
  // reader shares with, who appear nowhere else on the page.
  const openChannels = useMemo(() => {
    const connected = new Set((connectionsQuery.data?.accepted ?? []).map((g) => g.user_id));
    return (messagesQuery.data?.accepted ?? []).filter(
      (grant) => !connected.has(grant.user_id) && matches(grant)
    );
  }, [connectionsQuery.data, messagesQuery.data, matches]);

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
  const allValues = useMemo(
    () => [
      FAVORITES_VALUE,
      CONNECTIONS_VALUE,
      OPEN_CHANNELS_VALUE,
      ...sections.map((s) => `guild-${s.guild_id}`),
    ],
    [sections]
  );

  const openValues = useMemo(() => {
    if (searching) return allValues;
    const closed = new Set(collapse.closed);
    return allValues.filter((value) => !closed.has(value));
  }, [allValues, searching, collapse.closed]);

  const onOpenChange = useCallback(
    (next: string[]) => {
      if (searching) return;
      const open = new Set(next);
      setCollapse({ closed: allValues.filter((value) => !open.has(value)) });
    },
    [searching, allValues, setCollapse]
  );

  // Why the page is bare, if it is. Only worth saying while nothing is
  // searched for — under a term an empty page means the term, not the policy —
  // and only once the settings are in hand: absent, they read as an account
  // that has answered nothing, which is the one panel that must never be shown
  // to somebody who has.
  const reason =
    searching || !dmQuery.data
      ? null
      : unreachableReason(Boolean(dmQuery.data.age_confirmed_at), dmQuery.data.dm_policy);

  const isFirstLoad = sectionsQuery.isLoading || favoritesQuery.isLoading;
  // A term in flight, whether or not last term's answer is still on screen.
  const isSearchPending =
    searching && (isFirstLoad || sectionsQuery.isFetching || favoritesQuery.isFetching);
  const nothingAtAll =
    sections.length === 0 &&
    favorites.length === 0 &&
    connections.length === 0 &&
    openChannels.length === 0;

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

      {/* Above the table rather than inside it: an unanswered age closes
          messaging in both directions, so it is not a remark about the
          community sections. */}
      {reason === "age" ? <AgeUnansweredPanel /> : null}

      {/* Also above it, and only when something is waiting: a request is not a
          contact yet, it is a question — few, actionable and transient, which
          is not what the table below is for. The same section the Privacy tab
          renders, so there is one definition of what a request looks like and
          one set of answers to it. */}
      {pendingRequests > 0 ? (
        <section className="space-y-2 rounded-lg border p-4">
          <h2 className="font-medium text-sm">{t("requests")}</h2>
          <ContactRequestsSection whenEmpty={null} />
        </section>
      ) : null}

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
            {/* Under Favorites, because a link the reader made outranks the
                community that introduced them — and above the community
                sections for the same reason. */}
            {connections.length > 0 ? (
              <GrantContactSection
                key={`connections:${search}`}
                value={CONNECTIONS_VALUE}
                label={t("connections")}
                title={
                  <>
                    <Link2 className="size-4 text-muted-foreground" />
                    <span>{t("connections")}</span>
                  </>
                }
                items={connections}
                starredIds={starredIds}
                onToggleFavorite={toggleFavorite}
                guilds={guilds}
                emptyLabel={t("noMatches.section")}
              />
            ) : null}
            {openChannels.length > 0 ? (
              <GrantContactSection
                key={`open-channels:${search}`}
                value={OPEN_CHANNELS_VALUE}
                label={t("directMessages")}
                title={
                  <>
                    <MessageSquare className="size-4 text-muted-foreground" />
                    <span>{t("directMessages")}</span>
                  </>
                }
                items={openChannels}
                starredIds={starredIds}
                onToggleFavorite={toggleFavorite}
                guilds={guilds}
                emptyLabel={t("noMatches.section")}
              />
            ) : null}
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
          {/* Under the communities, which are the sections a policy empties.
              Favorites above it are the reader's own list and stay. */}
          {reason === "private" ? (
            <div className="pt-2">
              <PrivatePanel />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
};
