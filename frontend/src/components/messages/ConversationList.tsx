import { Link, useSearch } from "@tanstack/react-router";
import { ChevronRight, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContactGrantRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactActionsMenu } from "@/components/contacts/ContactActionsMenu";
import { PrivatePanel, unreachableReason } from "@/components/contacts/UnreachableEmptyState";
import { NewConversationDialog } from "@/components/messages/NewConversationDialog";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useFavoriteContacts } from "@/hooks/useContacts";
import {
  useAcceptConnection,
  useAcceptMessageRequest,
  useConnections,
  useDmPermissions,
  useDmSettings,
  useMessageRequests,
  useRemoveConnection,
  useRemoveMessageRequest,
} from "@/hooks/useDirectMessages";
import { useConversations, useUnreadMessages } from "@/hooks/useMyMessages";
import { getItem, setItem } from "@/lib/storage";
import { getUrlHandle, getUserHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

const ROW = "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-sm";

/**
 * The menu belongs to the row, not to the list: on a pointer it opens out of
 * the row's edge when the row is under the cursor, and it comes back whenever
 * it is focused or open, so a keyboard never chases a control it cannot see.
 * A touch screen has no hover to reveal it, so below `sm` it is simply there.
 *
 * It animates its *width* rather than only its opacity, the way the initiative
 * and project rows in the main sidebar do — so a name has the whole row until
 * somebody reaches for the menu, instead of being cut short all the time to
 * hold a space for something that is not on screen.
 */
const ROW_MENU = cn(
  "h-7 w-7 shrink-0 p-0",
  "motion-reduce:transition-none sm:w-0 sm:overflow-hidden sm:opacity-0 sm:transition-all",
  "sm:group-hover/row:w-7 sm:group-hover/row:opacity-100",
  "sm:group-focus-within/row:w-7 sm:group-focus-within/row:opacity-100",
  "sm:data-[state=open]:w-7 sm:data-[state=open]:opacity-100"
);

/** Which sections the reader has folded away. Remembered across visits. */
const COLLAPSED_KEY = "messages-groups-collapsed";

type GroupId = "unread" | "favorites" | "connections" | "messages";
const GROUP_ORDER: GroupId[] = ["unread", "favorites", "connections", "messages"];

/** One person this list can offer, whether or not a thread is open with them. */
interface Entry {
  userId: number;
  person: ContactGrantRead;
  /** Absent until a conversation has actually been opened with them. */
  conversationId?: string;
  waiting: number;
}

/**
 * Which agreement a pending request is part of — the only thing that differs
 * between two rows asking the reader the same question.
 */
type RequestKind = "connection" | "message";
interface PendingRequest {
  grant: ContactGrantRead;
  kind: RequestKind;
}

const readCollapsed = (): Record<string, boolean> => {
  try {
    return JSON.parse(getItem(COLLAPSED_KEY) ?? "{}") as Record<string, boolean>;
  } catch {
    return {};
  }
};

/**
 * Who there is to talk to, wherever that has to be offered.
 *
 * Drawn in two places on purpose. It is the sidebar's whole content on a wide
 * screen — and on a phone the sidebar shuts the moment you pick My Messages,
 * the way it does for every other destination, so the page it lands on has to
 * be the list rather than an apology for not being one. One component, so the
 * two cannot drift.
 *
 * Four sections, folded the way My Contacts folds its communities: people
 * waiting on an answer, people you starred, people you are connected to, and
 * everyone else you can reach. Unread comes first and takes precedence over
 * the rest — somebody has said something and nothing else on the list is
 * asking for anything. Below it a favourite outranks a connection, because
 * starring is a choice this reader made about this person and being connected
 * is only how the two of them are linked. A section with nobody in it is not
 * drawn, and where only one section has anybody it loses its heading — a label
 * naming everything says nothing.
 *
 * Above all of it, two controls that answer opposite questions. The field
 * narrows what is already here, on the handle, which is the one thing every
 * row carries — nothing is fetched for it and nobody new appears. Finding
 * somebody who is *not* here is the button beside it, which is why they sit
 * together.
 *
 * Every row addresses its person in the URL rather than holding a selection of
 * its own: the page already resolves `?with=` to a conversation, and a link is
 * what a back button, a middle click and a shared address all understand.
 */
export const ConversationList = () => {
  const { t } = useTranslation(["messages", "contacts"]);
  const { with: openHandle } = useSearch({ strict: false }) as { with?: string };
  const [term, setTerm] = useState("");

  const conversations = useConversations();
  const requests = useMessageRequests();
  const connections = useConnections();
  const settings = useDmSettings();

  const reachable = useMemo(() => requests.data?.accepted ?? [], [requests.data?.accepted]);
  const personFor = useMemo(
    () => new Map(reachable.map((grant) => [grant.user_id, grant])),
    [reachable]
  );

  const rows = useMemo(
    () => conversations.data?.conversations ?? [],
    [conversations.data?.conversations]
  );
  const unread = useUnreadMessages(rows.map((row) => row.id));

  // Somebody you may message but have not opened a channel with yet.
  const unopened = useMemo(
    () => reachable.filter((grant) => !rows.some((row) => row.other_user_id === grant.user_id)),
    [reachable, rows]
  );

  // Nothing is asked of the server for a term: every row here is already in
  // hand, and the handle is all any of them carries.
  const matches = useMemo(() => {
    const needle = term.trim().toLowerCase().replace(/^@/, "");
    return (person: ContactGrantRead) =>
      !needle || getUserHandle(person).toLowerCase().includes(needle);
  }, [term]);

  /**
   * Everything waiting on an answer, either way round and of either kind.
   *
   * Connection requests are here rather than only on My Contacts: to the
   * person reading it both kinds are the same question — somebody wants to be
   * able to talk and it has not started yet — and the mark that brought them
   * here never said which sort it was. Theirs first: those are the ones only
   * you can move. Yours are listed so an ask you sent does not look like it
   * never happened.
   */
  const waiting = useMemo(() => {
    const sources: [
      RequestKind,
      { incoming?: ContactGrantRead[]; outgoing?: ContactGrantRead[] } | undefined,
    ][] = [
      ["message", requests.data],
      ["connection", connections.data],
    ];
    const incoming: PendingRequest[] = [];
    const outgoing: PendingRequest[] = [];
    for (const [kind, data] of sources) {
      for (const grant of data?.incoming ?? []) incoming.push({ grant, kind });
      for (const grant of data?.outgoing ?? []) outgoing.push({ grant, kind });
    }
    return [...incoming, ...outgoing].filter(({ grant }) => matches(grant));
  }, [requests.data, connections.data, matches]);

  const acceptMessage = useAcceptMessageRequest();
  const declineMessage = useRemoveMessageRequest();
  const acceptConnection = useAcceptConnection();
  const declineConnection = useRemoveConnection();

  const accept = ({ grant, kind }: PendingRequest) =>
    kind === "connection"
      ? acceptConnection.mutate({ userId: grant.user_id })
      : acceptMessage.mutate({ userId: grant.user_id });

  const dismiss = ({ grant, kind }: PendingRequest) =>
    kind === "connection"
      ? declineConnection.mutate({ userId: grant.user_id })
      : declineMessage.mutate({ userId: grant.user_id });

  const answering =
    acceptMessage.isPending ||
    declineMessage.isPending ||
    acceptConnection.isPending ||
    declineConnection.isPending;

  // The two lists the sections are cut from. Both are reads My Contacts
  // already makes, so a reader who has been there pays nothing for them here.
  const favorites = useFavoriteContacts("");
  const starred = useMemo(
    () => new Set((favorites.data?.items ?? []).map((contact) => contact.id)),
    [favorites.data]
  );
  const connected = useMemo(
    () => new Set((connections.data?.accepted ?? []).map((grant) => grant.user_id)),
    [connections.data]
  );

  const entries: Entry[] = useMemo(
    () => [
      // Only conversations whose other side this reader can still see. A grant
      // that has lapsed -- they were ignored, or whatever let the two of you
      // talk has ended -- leaves a row with no name to show and no handle to
      // address, so listing it offers a person who cannot be opened. What this
      // device already collected stays on it either way.
      ...rows
        .filter((row) => personFor.has(row.other_user_id))
        .map((row) => ({
          userId: row.other_user_id,
          person: personFor.get(row.other_user_id) as ContactGrantRead,
          conversationId: row.id,
          waiting: unread.data?.get(row.id) ?? 0,
        })),
      ...unopened.map((grant) => ({ userId: grant.user_id, person: grant, waiting: 0 })),
    ],
    [rows, personFor, unopened, unread.data]
  );

  // One question about everybody listed, not one per row: what the menu on a
  // row can offer -- connecting, above all -- depends on the server's answer
  // about that person, and a list of them is a list of the same question.
  const permissions = useDmPermissions(useMemo(() => entries.map((e) => e.userId), [entries]));
  const answers = permissions.data?.permissions ?? {};

  const grouped = useMemo(() => {
    const groups: Record<GroupId, Entry[]> = {
      unread: [],
      favorites: [],
      connections: [],
      messages: [],
    };
    for (const entry of entries.filter((entry) => matches(entry.person))) {
      // Unread wins over where somebody otherwise belongs, so a starred person
      // with something waiting is read here rather than found further down.
      const group = entry.waiting
        ? "unread"
        : starred.has(entry.userId)
          ? "favorites"
          : connected.has(entry.userId)
            ? "connections"
            : "messages";
      groups[group].push(entry);
    }
    return groups;
  }, [entries, starred, connected, matches]);

  const [collapsed, setCollapsed] = useState(readCollapsed);
  const fold = (group: GroupId, open: boolean) => {
    const next = { ...collapsed, [group]: !open };
    setCollapsed(next);
    setItem(COLLAPSED_KEY, JSON.stringify(next));
  };

  const filled = GROUP_ORDER.filter((group) => grouped[group].length > 0);
  const searching = term.trim().length > 0;
  const reason = settings.data
    ? unreachableReason(Boolean(settings.data.age_confirmed_at), settings.data.dm_policy)
    : null;
  // A folded section under a term would hide the one match that was looked
  // for. The reader's own state is left untouched, so clearing the field puts
  // the sections back the way they had them.
  const isOpen = (group: GroupId) => searching || !collapsed[group];

  // Whether there is anything to narrow, asked of what the account has rather
  // than of what is left after typing — so the field does not disappear under
  // the cursor on a term that matches nobody.
  const anything =
    entries.length +
      (requests.data?.incoming?.length ?? 0) +
      (requests.data?.outgoing?.length ?? 0) +
      (connections.data?.incoming?.length ?? 0) +
      (connections.data?.outgoing?.length ?? 0) >
    0;

  const listFor = (entries: Entry[]) => (
    <ul>
      {entries.map((entry) => {
        const them = entry.person;
        const handle = getUrlHandle(them);
        return (
          <li
            key={entry.conversationId ?? `u${entry.userId}`}
            className={cn(
              "group/row flex items-center rounded-md pe-1 hover:bg-accent",
              handle === openHandle && "bg-accent"
            )}
          >
            <Link
              to="/messages"
              search={{ with: handle }}
              className={cn(ROW, !entry.conversationId && "text-muted-foreground")}
            >
              <ProfileAvatar
                user={{ ...them, id: them.user_id }}
                decorations={them.profile_decorations}
                presence={them.presence}
                className="size-6"
              />
              <UserHandle
                user={them}
                className="min-w-0 flex-1"
                nameClassName="min-w-0 truncate"
                numberClassName="shrink-0"
              />
              {/* A dot carries no text, so the count it stands for is written
                  out for anyone not looking at it. */}
              {entry.waiting ? (
                <span className="relative ms-auto flex shrink-0 items-center">
                  <span className="sr-only">{t("unreadHere", { count: entry.waiting })}</span>
                  <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
                </span>
              ) : null}
              {!entry.conversationId ? (
                <span className="shrink-0 text-xs">{t("startHint")}</span>
              ) : null}
            </Link>
            {/* Outside the link, because acting on somebody is not the same
                gesture as opening what they said. The ways in are left out:
                the row is one, and clicking it is the conversation. */}
            <ContactActionsMenu
              user={{
                id: them.user_id,
                username: them.username,
                discriminator: them.discriminator,
              }}
              className={ROW_MENU}
              permission={answers[String(them.user_id)] ?? null}
              omit={["message"]}
            />
          </li>
        );
      })}
    </ul>
  );

  return (
    <div className="space-y-3">
      {/* Drawn before anything is known, and before the loading line below:
          an account with nobody in it is exactly the one that needs the way
          to find somebody. */}
      <div className="flex items-center gap-1 px-2">
        {anything ? (
          <div className="relative min-w-0 flex-1">
            <Search
              className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder={t("search.placeholder")}
              aria-label={t("search.label")}
              className="h-8 ps-7 text-sm"
            />
          </div>
        ) : (
          <div className="min-w-0 flex-1" />
        )}
        <NewConversationDialog />
      </div>

      {conversations.isLoading ? (
        <p className="px-2 py-1 text-muted-foreground text-sm">{t("loading")}</p>
      ) : (
        <>
          {waiting.length > 0 ? (
            <section>
              <h3 className="px-2 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
                {t("requests.heading")}
              </h3>
              <ul className="space-y-2 px-2 py-1">
                {waiting.map((row) => {
                  const { grant, kind } = row;
                  return (
                    <li key={`${kind}-${grant.user_id}`}>
                      <div className="flex items-center gap-2">
                        <ProfileAvatar
                          user={{ ...grant, id: grant.user_id }}
                          decorations={grant.profile_decorations}
                          presence={grant.presence}
                          className="size-7"
                        />
                        <UserHandle
                          user={grant}
                          className="min-w-0 flex-1 text-sm"
                          nameClassName="min-w-0 truncate"
                          numberClassName="shrink-0"
                        />
                        {/* Withdrawing your own ask and declining theirs are the
                            same write, so an outgoing row offers only that one --
                            and one button is a trailing action on the name rather
                            than a full-width bar stranded under it. */}
                        {grant.outgoing ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 shrink-0 px-2 text-xs"
                            disabled={answering}
                            onClick={() => dismiss(row)}
                          >
                            {t("requests.cancel")}
                          </Button>
                        ) : null}
                      </div>
                      {/* What they asked for: the one thing the two kinds do not
                          have in common, and the one that decides what accepting
                          it opens. */}
                      <p className="mt-1 text-muted-foreground text-xs">
                        {t(
                          grant.outgoing
                            ? kind === "connection"
                              ? "requests.youAskedToConnect"
                              : "requests.youAsked"
                            : kind === "connection"
                              ? "requests.wantsToConnect"
                              : "requests.asked"
                        )}
                      </p>
                      {grant.outgoing ? null : (
                        <div className="mt-1.5 flex gap-1.5">
                          <Button
                            size="sm"
                            className="h-7 flex-1"
                            disabled={answering}
                            onClick={() => accept(row)}
                          >
                            {t("requests.accept")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 flex-1"
                            disabled={answering}
                            onClick={() => dismiss(row)}
                          >
                            {t("requests.decline")}
                          </Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          {filled.length === 0 ? (
            searching ? (
              // Only when the term found nothing at all. A request matching it
              // is drawn above, and saying "nobody matches" over the top of
              // somebody's name contradicts the page.
              waiting.length === 0 ? (
                <p className="px-2 py-1 text-muted-foreground text-sm">{t("search.noMatches")}</p>
              ) : null
            ) : /* Why it is empty, where the reason is the reader's own settings
                   rather than an absence of people. Nothing is guessed before
                   the settings arrive: absent, they read as an account that has
                   answered nothing, which is the one thing that must never be
                   shown to somebody who has. */
            reason === "age" ? (
              <div className="space-y-2 px-2 py-1">
                <p className="text-muted-foreground text-sm">{t("ageLocked")}</p>
                <Button variant="outline" size="sm" asChild>
                  <Link to="/profile/privacy">{t("contacts:unreachable.private.settings")}</Link>
                </Button>
              </div>
            ) : reason === "private" ? (
              <div className="px-2 py-1">
                <PrivatePanel />
              </div>
            ) : waiting.length === 0 ? (
              <p className="px-2 py-1 text-muted-foreground text-sm">{t("nobodyYet")}</p>
            ) : null
          ) : /* One section with everybody in it is just the list, so it is drawn
                as the list: nothing to fold, and no heading naming "all of them". */
          filled.length === 1 ? (
            listFor(grouped[filled[0]])
          ) : (
            filled.map((group) => (
              <Collapsible
                key={group}
                open={isOpen(group)}
                onOpenChange={(open) => fold(group, open)}
              >
                <CollapsibleTrigger className="flex w-full items-center gap-1 rounded-md px-2 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide hover:bg-accent">
                  <ChevronRight
                    className={cn("size-3.5 transition-transform", isOpen(group) && "rotate-90")}
                    aria-hidden
                  />
                  <span className="flex-1 text-left">{t(`groups.${group}`)}</span>
                  <span className="tabular-nums">{grouped[group].length}</span>
                </CollapsibleTrigger>
                <CollapsibleContent>{listFor(grouped[group])}</CollapsibleContent>
              </Collapsible>
            ))
          )}
        </>
      )}
    </div>
  );
};
