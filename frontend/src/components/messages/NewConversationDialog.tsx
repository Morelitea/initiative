import { useNavigate } from "@tanstack/react-router";
import { MessageSquarePlus, Star } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ContactGuildSection,
  ContactRead,
  DirectMessagePermissionRead,
} from "@/api/generated/initiativeAPI.schemas";
import { ContactActionsMenu } from "@/components/contacts/ContactActionsMenu";
import { FavoriteToggle } from "@/components/contacts/FavoriteToggle";
import { UserHandle } from "@/components/UserHandle";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import {
  useContactSections,
  useFavoriteContacts,
  useMoreCommunityContacts,
  useToggleFavoriteContact,
} from "@/hooks/useContacts";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { parseHandle, useDmPermissions, useRequestConnection } from "@/hooks/useDirectMessages";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { getInitials } from "@/lib/initials";
import { getUrlHandle, getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

/** How long typing settles before the roster follows it. */
const SEARCH_SETTLES_MS = 250;

/**
 * Somebody who is not in the list yet.
 *
 * The conversation list can only offer people it already has — the ones who
 * agreed to hear from you. Everybody else is reached from here, and there are
 * exactly two ways to name them, which is why they share one field. Typing
 * narrows the people you starred and the communities you are in. Typing a
 * whole handle, number included, also offers a connection: that is the one
 * shape that reaches an account no roster of yours will ever list.
 *
 * This is what My Contacts used to be, minus the browsing: that page listed
 * everyone you shared a community with, and the only thing anybody did from a
 * row was reach for one of them.
 *
 * Picking somebody navigates rather than acting. A row is not a promise that a
 * channel exists — most of the people it lists have never agreed to anything —
 * and the page it lands on is the one that already knows how to say so and
 * what to offer instead.
 */
export const NewConversationDialog = () => {
  const { t } = useTranslation(["messages", "contacts", "settings"]);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [error, setError] = useState<string | null>(null);

  // The field answers every keystroke; the request waits for typing to stop.
  const settled = useDebouncedValue(term, SEARCH_SETTLES_MS);
  // Not until it is opened: the aggregate walks every community the reader
  // is in, and a button nobody has pressed is no reason to walk them.
  const sections = useContactSections(settled, { enabled: open });

  const groups = useMemo(() => sections.data?.sections ?? [], [sections.data]);
  const ids = useMemo(() => {
    const seen = new Set<number>();
    for (const group of groups) {
      for (const person of group.items) seen.add(person.id);
    }
    return [...seen];
  }, [groups]);
  // One question for everybody on screen, not one per row.
  const permissions = useDmPermissions(open ? ids : []);
  const answers = permissions.data?.permissions ?? {};

  const requestConnection = useRequestConnection();
  // Only a whole handle is a connection: half of one is a search term.
  const handle = parseHandle(term);

  const close = () => {
    setOpen(false);
    setTerm("");
    setError(null);
  };

  const pick = (person: ContactRead) => {
    close();
    void navigate({ to: "/messages", search: { with: getUrlHandle(person) } });
  };

  const connect = () => {
    if (!handle) return;
    setError(null);
    requestConnection.mutate(
      { data: handle },
      {
        onSuccess: () => {
          toast.success(t("settings:privacy.connections.sent"));
          close();
        },
        onError: (err) => setError(getErrorMessage(err, "errors:CONTACT_GRANT_CANNOT_REACH")),
      }
    );
  };

  // Whether there is anybody at all to offer -- favourites included, since a
  // reader who shares no community with anyone may still have starred people.
  const starred = useFavoriteContacts(settled, { enabled: open });
  const starredPeople = useMemo(() => starred.data?.items ?? [], [starred.data]);
  const starredIds = useMemo(
    () => new Set(starredPeople.map((person) => person.id)),
    [starredPeople]
  );
  const anybody = groups.some((group) => group.items.length > 0) || starredPeople.length > 0;

  const setFavorite = useToggleFavoriteContact();
  const toggleFavorite = (person: ContactRead) => setFavorite(person.id, starredIds.has(person.id));

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setOpen(true);
        else close();
      }}
    >
      {/* The one thing on this column that starts something rather than
          narrowing what is already there, so it is the one thing drawn as a
          filled button. The name is inside it for a screen reader either way;
          the tooltip is for everybody else, since an icon alone says "add"
          without saying add what. */}
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DialogTrigger asChild>
              <Button size="icon" className="size-8 shrink-0">
                <MessageSquarePlus className="size-4" aria-hidden />
                <span className="sr-only">{t("messages:newConversation.trigger")}</span>
              </Button>
            </DialogTrigger>
          </TooltipTrigger>
          <TooltipContent side="top">{t("messages:newConversation.trigger")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("messages:newConversation.title")}</DialogTitle>
          <DialogDescription>{t("messages:newConversation.description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-1">
          <Input
            autoFocus
            value={term}
            onChange={(event) => {
              setTerm(event.target.value);
              setError(null);
            }}
            placeholder={t("messages:newConversation.placeholder")}
            aria-label={t("messages:newConversation.placeholder")}
            onKeyDown={(event) => {
              if (event.key === "Enter" && handle) connect();
            }}
          />
          <p className={error ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
            {error ?? t("messages:newConversation.hint")}
          </p>
        </div>

        {/* Above the rosters, because it is about somebody who is not in them.
            It appears only once the handle is whole: a connection is addressed
            by the exact name and number, and half of one addresses nobody. */}
        {handle ? (
          <Button
            variant="outline"
            className="w-full justify-start"
            disabled={requestConnection.isPending}
            onClick={connect}
          >
            {t("messages:newConversation.connect", {
              handle: `${handle.username}#${String(handle.discriminator).padStart(4, "0")}`,
            })}
          </Button>
        ) : null}

        <div className="-mx-2 max-h-80 overflow-y-auto px-2">
          {sections.isLoading || starred.isLoading ? (
            <p className="py-2 text-muted-foreground text-sm">{t("messages:loading")}</p>
          ) : !anybody ? (
            <p className="py-2 text-muted-foreground text-sm">
              {settled.trim()
                ? t("messages:newConversation.noMatches")
                : t("messages:newConversation.empty")}
            </p>
          ) : (
            <div className="space-y-3">
              <FavoriteRoster
                items={starredPeople}
                answers={answers}
                onPick={pick}
                onToggleFavorite={toggleFavorite}
              />
              {groups
                .filter((group) => group.items.length > 0)
                .map((group) => (
                  <CommunityRoster
                    // Remounted on a new term, which is what puts a community
                    // somebody expanded back to its first page: under a
                    // different term it is a different set of people, and
                    // carrying the expansion over would fetch a second page
                    // nobody asked for.
                    key={`${group.guild_id}:${settled}`}
                    section={group}
                    search={settled}
                    answers={answers}
                    starred={starredIds}
                    onPick={pick}
                    onToggleFavorite={toggleFavorite}
                  />
                ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

/**
 * One community's people, grown rather than paged.
 *
 * A picker is read downwards: stepping between pages would take away the row
 * somebody had just spotted, so *Show more* appends. Page one arrives with the
 * walk the dialog already made; everything after it is this community's own
 * request, and only once somebody asks.
 *
 * It answers for its own extra rows too. The dialog asks one question about
 * everybody the walk returned, which is the whole of what most readers ever
 * see; anybody past that is this section's to ask about.
 */
const CommunityRoster = ({
  section,
  search,
  answers,
  starred,
  onPick,
  onToggleFavorite,
}: {
  section: ContactGuildSection;
  search: string;
  answers: Record<string, DirectMessagePermissionRead>;
  starred: Set<number>;
  onPick: (person: ContactRead) => void;
  onToggleFavorite: (person: ContactRead) => void;
}) => {
  const { t } = useTranslation(["messages", "contacts"]);
  const [wantsMore, setWantsMore] = useState(false);
  const more = useMoreCommunityContacts(section.guild_id, search, wantsMore);

  const extra = useMemo(
    () => more.data?.pages.flatMap((page) => page.sections?.[0]?.items ?? []) ?? [],
    [more.data]
  );
  const extraAnswers = useDmPermissions(useMemo(() => extra.map((p) => p.id), [extra]));
  const answerFor = (id: number) =>
    answers[String(id)] ?? extraAnswers.data?.permissions?.[String(id)];

  // Still more to come until this community says otherwise. While a page is on
  // its way the button stays, disabled, rather than vanishing and returning.
  const exhausted = wantsMore && more.isSuccess && !more.hasNextPage;
  const hasMore = section.has_next && !exhausted;

  return (
    <section>
      <h3 className="flex items-center gap-1.5 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
        {/* Decorative: its fallback is the community's own initials, which
            would otherwise be read out in front of the name it stands for. */}
        <Avatar aria-hidden className="size-4 rounded-md">
          {section.icon_url ? <AvatarImage src={section.icon_url} alt="" /> : null}
          <AvatarFallback className="rounded-md bg-muted text-[0.55rem] text-muted-foreground">
            {getInitials(section.guild_name, "G")}
          </AvatarFallback>
        </Avatar>
        <span className="min-w-0 flex-1 truncate">{section.guild_name}</span>
        <span className="shrink-0 tabular-nums">{section.total_count}</span>
      </h3>
      <ul>
        {[...section.items, ...extra].map((person) => {
          const answer = answerFor(person.id);
          return (
            <PickerPerson
              key={person.id}
              person={person}
              answer={answer}
              starred={starred.has(person.id)}
              onPick={onPick}
              onToggleFavorite={onToggleFavorite}
            />
          );
        })}
      </ul>
      {hasMore ? (
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          disabled={more.isFetching}
          onClick={() => (wantsMore ? void more.fetchNextPage() : setWantsMore(true))}
        >
          {t("messages:newConversation.showMore")}
        </Button>
      ) : null}
    </section>
  );
};

/**
 * One person, offered.
 *
 * Every refusal collapses into one word server-side, so a row built from it
 * cannot say which refusal it is -- and does not try. It simply stops being a
 * way in.
 */
const PickerPerson = ({
  person,
  answer,
  starred,
  onPick,
  onToggleFavorite,
}: {
  person: ContactRead;
  answer: DirectMessagePermissionRead | undefined;
  starred: boolean;
  onPick: (person: ContactRead) => void;
  onToggleFavorite: (person: ContactRead) => void;
}) => {
  const { t } = useTranslation(["messages", "contacts"]);
  const denied = answer?.permission === "denied";

  return (
    <li className="flex items-center gap-1">
      <button
        type="button"
        disabled={denied}
        onClick={() => onPick(person)}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-sm",
          denied ? "cursor-default opacity-60" : "hover:bg-accent"
        )}
      >
        <ProfileAvatar
          user={person}
          decorations={person.profile_decorations}
          presence={person.presence}
          className="size-6"
        />
        <UserHandle
          user={person}
          className="min-w-0 flex-1"
          nameClassName="min-w-0 truncate"
          numberClassName="shrink-0"
        />
        <span className="shrink-0 text-muted-foreground text-xs">
          {denied
            ? t("messages:newConversation.unreachable")
            : answer?.permission === "may_request"
              ? t("contacts:actions.ask")
              : null}
        </span>
      </button>
      {/* Outside the button, and outside its `disabled`. For somebody you
          share no community with, this dialog is the only place they appear
          at all -- so if the way in is shut, everything else you might do
          about them has to still be open: unstar them, go and look at them,
          connect, ignore. */}
      <FavoriteToggle
        starred={starred}
        name={getUserDisplayName(person)}
        onToggle={() => onToggleFavorite(person)}
      />
      <ContactActionsMenu
        user={{
          id: person.id,
          username: person.username,
          discriminator: person.discriminator,
        }}
        className="size-8 shrink-0"
        permission={answer ?? null}
        // The row is the way in and the star is beside it. Everything else
        // the menu holds -- the profile above all -- is only here.
        omit={["message", "ask", "favorite"]}
      />
    </li>
  );
};

/**
 * The people this reader starred, above the communities.
 *
 * Starring is the one list that is not a slice of anything: a favourite may be
 * somebody you share no community with, so no roster below will ever hold
 * them. Without this they would be reachable only by typing their handle from
 * memory -- and somebody who starred a person is exactly somebody who expects
 * to find them again.
 *
 * A favourite you *do* share a community with appears twice, here and there.
 * That is what a shortcut is; carving them out of the rosters would leave the
 * paged ones with holes in them.
 */
const FavoriteRoster = ({
  items,
  answers,
  onPick,
  onToggleFavorite,
}: {
  items: ContactRead[];
  answers: Record<string, DirectMessagePermissionRead>;
  onPick: (person: ContactRead) => void;
  onToggleFavorite: (person: ContactRead) => void;
}) => {
  const { t } = useTranslation("messages");
  const own = useDmPermissions(useMemo(() => items.map((person) => person.id), [items]));

  if (items.length === 0) return null;

  return (
    <section>
      <h3 className="flex items-center gap-1.5 py-1 font-medium text-muted-foreground text-xs uppercase tracking-wide">
        <Star className="size-3.5 shrink-0 fill-amber-400 text-amber-500" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{t("newConversation.favorites")}</span>
      </h3>
      <ul>
        {items.map((person) => (
          <PickerPerson
            key={person.id}
            person={person}
            // The dialog's own question covers whoever is also in a roster;
            // the rest are this section's to ask about.
            answer={answers[String(person.id)] ?? own.data?.permissions?.[String(person.id)]}
            starred
            onPick={onPick}
            onToggleFavorite={onToggleFavorite}
          />
        ))}
      </ul>
    </section>
  );
};
