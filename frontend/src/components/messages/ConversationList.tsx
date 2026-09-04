import { Link, useSearch } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContactGrantRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useFavoriteContacts } from "@/hooks/useContacts";
import {
  useAcceptMessageRequest,
  useConnections,
  useMessageRequests,
  useRemoveMessageRequest,
} from "@/hooks/useDirectMessages";
import { useConversations, useUnreadMessages } from "@/hooks/useMyMessages";
import { getItem, setItem } from "@/lib/storage";
import { getUrlHandle, getUserHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

const ROW = "flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm hover:bg-accent";

/** Which sections the reader has folded away. Remembered across visits. */
const COLLAPSED_KEY = "messages-groups-collapsed";

type GroupId = "favorites" | "connections" | "messages";
const GROUP_ORDER: GroupId[] = ["favorites", "connections", "messages"];

/** One person this list can offer, whether or not a thread is open with them. */
interface Entry {
  userId: number;
  person: ContactGrantRead;
  /** Absent until a conversation has actually been opened with them. */
  conversationId?: string;
  waiting: number;
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
 * Three sections, folded the way My Contacts folds its communities: people you
 * starred, people you are connected to, and everyone else you can reach. A
 * favourite outranks a connection, because starring is a choice this reader
 * made about this person and being connected is only how the two of them are
 * linked. A section with nobody in it is not drawn, and where only one section
 * has anybody it loses its heading — a label naming everything says nothing.
 *
 * Every row addresses its person in the URL rather than holding a selection of
 * its own: the page already resolves `?with=` to a conversation, and a link is
 * what a back button, a middle click and a shared address all understand.
 */
export const ConversationList = () => {
  const { t } = useTranslation("messages");
  const { with: openHandle } = useSearch({ strict: false }) as { with?: string };

  const conversations = useConversations();
  const requests = useMessageRequests();

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
  /**
   * Everything waiting on an answer, either way round.
   *
   * Both directions in one section because they are the same question to the
   * person reading it -- somebody wants a conversation and it has not started
   * yet. Theirs first: those are the ones only you can move. Yours are listed
   * so an ask you sent does not look like it never happened.
   */
  const waiting = useMemo(
    () =>
      [...(requests.data?.incoming ?? []), ...(requests.data?.outgoing ?? [])].map((grant) => ({
        grant,
        // The grant says which of the two asked, so the row reads it off the
        // row rather than off the list it arrived in. One fact, one place.
        outgoing: grant.outgoing,
      })),
    [requests.data?.incoming, requests.data?.outgoing]
  );

  const acceptRequest = useAcceptMessageRequest();
  const declineRequest = useRemoveMessageRequest();

  // The two lists the sections are cut from. Both are reads My Contacts
  // already makes, so a reader who has been there pays nothing for them here.
  const favorites = useFavoriteContacts("");
  const connections = useConnections();
  const starred = useMemo(
    () => new Set((favorites.data?.items ?? []).map((contact) => contact.id)),
    [favorites.data]
  );
  const connected = useMemo(
    () => new Set((connections.data?.accepted ?? []).map((grant) => grant.user_id)),
    [connections.data]
  );

  const grouped = useMemo(() => {
    const entries: Entry[] = [
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
    ];
    const groups: Record<GroupId, Entry[]> = { favorites: [], connections: [], messages: [] };
    for (const entry of entries) {
      const group = starred.has(entry.userId)
        ? "favorites"
        : connected.has(entry.userId)
          ? "connections"
          : "messages";
      groups[group].push(entry);
    }
    return groups;
  }, [rows, unopened, personFor, unread.data, starred, connected]);

  const [collapsed, setCollapsed] = useState(readCollapsed);
  const fold = (group: GroupId, open: boolean) => {
    const next = { ...collapsed, [group]: !open };
    setCollapsed(next);
    setItem(COLLAPSED_KEY, JSON.stringify(next));
  };

  const filled = GROUP_ORDER.filter((group) => grouped[group].length > 0);

  if (conversations.isLoading) {
    return <p className="px-2 py-1 text-muted-foreground text-sm">{t("loading")}</p>;
  }

  if (filled.length === 0 && waiting.length === 0) {
    return <p className="px-2 py-1 text-muted-foreground text-sm">{t("nobodyYet")}</p>;
  }

  const listFor = (entries: Entry[]) => (
    <ul>
      {entries.map((entry) => {
        const them = entry.person;
        const handle = getUrlHandle(them);
        return (
          <li key={entry.conversationId ?? `u${entry.userId}`}>
            <Link
              to="/messages"
              search={{ with: handle }}
              className={cn(
                ROW,
                !entry.conversationId && "text-muted-foreground",
                handle === openHandle && "bg-accent"
              )}
            >
              <ProfileAvatar
                user={{ ...them, id: them.user_id }}
                decorations={them.profile_decorations}
                presence={them.presence}
                className="size-6"
              />
              <span className="min-w-0 flex-1 truncate">{getUserHandle(them)}</span>
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
          </li>
        );
      })}
    </ul>
  );

  return (
    <div className="space-y-3">
      {waiting.length > 0 ? (
        <section>
          <h3 className="px-2 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
            {t("requests.heading")}
          </h3>
          <ul className="space-y-2 px-2 py-1">
            {waiting.map(({ grant, outgoing }) => (
              <li key={grant.user_id}>
                <div className="flex items-center gap-2">
                  <ProfileAvatar
                    user={{ ...grant, id: grant.user_id }}
                    decorations={grant.profile_decorations}
                    presence={grant.presence}
                    className="size-7"
                  />
                  <span className="min-w-0 flex-1 truncate text-sm">{getUserHandle(grant)}</span>
                  {/* Withdrawing your own ask and declining theirs are the same
                      write, so an outgoing row offers only that one -- and one
                      button is a trailing action on the name rather than a
                      full-width bar stranded under it. */}
                  {outgoing ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 shrink-0 px-2 text-xs"
                      disabled={declineRequest.isPending}
                      onClick={() => declineRequest.mutate({ userId: grant.user_id })}
                    >
                      {t("requests.cancel")}
                    </Button>
                  ) : null}
                </div>
                <p className="mt-1 text-muted-foreground text-xs">
                  {t(outgoing ? "requests.youAsked" : "requests.asked")}
                </p>
                {outgoing ? null : (
                  <div className="mt-1.5 flex gap-1.5">
                    <Button
                      size="sm"
                      className="h-7 flex-1"
                      disabled={acceptRequest.isPending}
                      onClick={() => acceptRequest.mutate({ userId: grant.user_id })}
                    >
                      {t("requests.accept")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 flex-1"
                      disabled={declineRequest.isPending}
                      onClick={() => declineRequest.mutate({ userId: grant.user_id })}
                    >
                      {t("requests.decline")}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* One section with everybody in it is just the list, so it is drawn as
          the list: nothing to fold, and no heading naming "all of them". */}
      {filled.length === 1
        ? listFor(grouped[filled[0]])
        : filled.map((group) => (
            <Collapsible
              key={group}
              open={!collapsed[group]}
              onOpenChange={(open) => fold(group, open)}
            >
              <CollapsibleTrigger className="flex w-full items-center gap-1 rounded-md px-2 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide hover:bg-accent">
                <ChevronRight
                  className={cn("size-3.5 transition-transform", !collapsed[group] && "rotate-90")}
                  aria-hidden
                />
                <span className="flex-1 text-left">{t(`groups.${group}`)}</span>
                <span className="tabular-nums">{grouped[group].length}</span>
              </CollapsibleTrigger>
              <CollapsibleContent>{listFor(grouped[group])}</CollapsibleContent>
            </Collapsible>
          ))}
    </div>
  );
};
