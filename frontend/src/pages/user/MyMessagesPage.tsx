import { useNavigate, useSearch } from "@tanstack/react-router";
import { MessageSquare, Send, ShieldCheck, UserX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { StartWithPerson } from "@/components/messages/StartWithPerson";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ratchetSupported } from "@/crypto/client";
import { RecipientHasNoDeviceError } from "@/crypto/messaging";
import { useMessageRequests } from "@/hooks/useDirectMessages";
import {
  useCollectMessages,
  useConversations,
  useDmDevice,
  useMarkThreadRead,
  useSendMessage,
  useStartConversation,
  useThread,
  useUnreadMessages,
} from "@/hooks/useMyMessages";
import { useUserProfile } from "@/hooks/useUsers";
import { getUrlHandle, getUserHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

/**
 * My Messages — the conversations this account has open, read on this device.
 *
 * Two things about this page are unlike every other list in the product:
 *
 * * **The thread comes out of local storage, not an endpoint.** The server
 *   deletes a message once this device has collected it, so what is on screen
 *   is what this device decrypted and wrote down.
 * * **A device that has never been here has no history.** That is what forward
 *   secrecy costs, and the page says so rather than looking broken.
 *
 * It is also the page a contacts row points at, via `?with=<handle>`. Most of
 * the people it can be opened for have no channel yet — a contact is somebody
 * you share a community with, not somebody who agreed to hear from you — so the
 * handle is a request to open a conversation, and what comes back may be the
 * offer to ask for one instead.
 */
export function MyMessagesPage() {
  const { t } = useTranslation("messages");
  const device = useDmDevice();
  const conversations = useConversations();
  const requests = useMessageRequests();
  const startConversation = useStartConversation();
  const [selected, setSelected] = useState<string | null>(null);

  // Who the URL asked for, resolved to a person. The profile is what a panel
  // for somebody with no channel has to draw, and the id is what everything
  // else here is keyed on.
  const { with: withHandle } = useSearch({ strict: false }) as { with?: string };
  const target = useUserProfile(withHandle);

  useCollectMessages(device.isSuccess);

  /** Everyone with an accepted channel, whether or not it has been opened. */
  const reachable = useMemo(() => requests.data?.accepted ?? [], [requests.data?.accepted]);
  // The whole grant rather than a name: a row in this list draws a person, and
  // a person is their picture and what they wear on it as much as their handle.
  const personFor = useMemo(
    () => new Map(reachable.map((grant) => [grant.user_id, grant])),
    [reachable]
  );

  /** What to call the other side of a conversation, wherever it is named. */
  const nameOf = (userId: number) => {
    const person = personFor.get(userId);
    return person ? getUserHandle(person) : t("unknownAccount");
  };

  const rows = conversations.data?.conversations ?? [];
  const current = rows.find((row) => row.id === selected) ?? null;

  // What has arrived since this device last opened each thread. Local, because
  // the thread is: the server deletes a message once it has been collected.
  const unread = useUnreadMessages(rows.map((row) => row.id));

  // Somebody you may message but have not opened a channel with yet.
  const unopened = reachable.filter(
    (grant) => !rows.some((row) => row.other_user_id === grant.user_id)
  );

  const targetId = target.data?.id;
  const targetConversation = rows.find((row) => row.other_user_id === targetId);
  const channelOpen = targetId !== undefined && personFor.has(targetId);

  // Acting on the handle in the URL, once per handle: select their thread, or
  // open one where the channel is already there. A conversation is one per
  // pair server-side, so asking for one that exists returns it rather than a
  // second — which is what makes this safe to fire from an effect.
  //
  // Not before the list has arrived, though: until then every conversation
  // looks missing, and opening one that is already there is a round trip to be
  // told what was on its way.
  const opened = useRef<string | null>(null);
  const startMessages = startConversation.mutate;
  const conversationsLoaded = conversations.isSuccess;

  // Whose open failed, not merely that one did: a mutation has one error state
  // and the reader moves on to somebody else, who would otherwise arrive at a
  // failure that was never theirs.
  const [failedFor, setFailedFor] = useState<string | null>(null);

  const openWith = useCallback(
    (userId: number, handle: string) =>
      startMessages(userId, {
        onSuccess: (conversation) => {
          setFailedFor(null);
          setSelected(conversation.id);
        },
        onError: () => setFailedFor(handle),
      }),
    [startMessages]
  );

  useEffect(() => {
    if (!withHandle || targetId === undefined || !conversationsLoaded) return;
    if (opened.current === withHandle) return;
    if (targetConversation) {
      opened.current = withHandle;
      setSelected(targetConversation.id);
      return;
    }
    if (channelOpen) {
      opened.current = withHandle;
      openWith(targetId, withHandle);
    }
  }, [withHandle, targetId, targetConversation, channelOpen, conversationsLoaded, openWith]);

  const navigate = useNavigate();

  /**
   * Open a thread, and address it in the URL.
   *
   * Everything the sidebar lists is somebody whose handle is known, so picking
   * one is the same gesture as arriving from a contacts row and the address
   * bar says the same thing either way. A conversation whose grant is gone has
   * no handle left to write, and clears it instead.
   */
  const open = (
    conversationId: string | null,
    person?: { username: string; discriminator: number }
  ) => {
    setSelected(conversationId);
    void navigate({
      to: ".",
      search: person ? { with: getUrlHandle(person) } : {},
      replace: true,
    });
  };

  // A runtime with no web workers cannot hold a ratchet at all, and saying so
  // is more use than the generic failure it would otherwise reach.
  if (!ratchetSupported()) {
    return (
      <div className="p-6">
        <StatusMessage
          icon={<ShieldCheck className="size-6" aria-hidden />}
          title={t("unsupportedBrowser")}
        />
      </div>
    );
  }

  if (device.isError) {
    return (
      <div className="p-6">
        <StatusMessage
          icon={<ShieldCheck className="size-6" aria-hidden />}
          title={t("deviceFailed")}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b px-6 py-4">
        <h1 className="font-semibold text-xl">{t("title")}</h1>
        <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
          <ShieldCheck className="size-3.5" aria-hidden />
          {t("encryptedNotice")}
        </p>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 overflow-y-auto border-r">
          {conversations.isLoading ? (
            <p className="p-4 text-muted-foreground text-sm">{t("loading")}</p>
          ) : rows.length === 0 && unopened.length === 0 ? (
            <p className="p-4 text-muted-foreground text-sm">{t("nobodyYet")}</p>
          ) : (
            <ul>
              {rows.map((row) => {
                const person = personFor.get(row.other_user_id);
                return (
                  <li key={row.id}>
                    <button
                      type="button"
                      onClick={() => open(row.id, person)}
                      className={cn(
                        "flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-accent",
                        row.id === selected && "bg-accent"
                      )}
                    >
                      {person ? (
                        <ProfileAvatar
                          user={person}
                          decorations={person.profile_decorations}
                          presence={person.presence}
                          className="size-8"
                        />
                      ) : null}
                      <span className="min-w-0 flex-1 truncate">{nameOf(row.other_user_id)}</span>
                      {/* The same mark the sidebar puts on My Messages, saying
                          which thread put it there. */}
                      {unread.data?.get(row.id) ? (
                        <span className="flex shrink-0 items-center">
                          <span className="sr-only">
                            {t("unreadHere", { count: unread.data.get(row.id) })}
                          </span>
                          <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
              {unopened.map((grant) => (
                <li key={grant.user_id}>
                  <button
                    type="button"
                    disabled={startConversation.isPending}
                    onClick={() => open(null, grant)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left text-muted-foreground text-sm hover:bg-accent"
                  >
                    <ProfileAvatar
                      user={grant}
                      decorations={grant.profile_decorations}
                      presence={grant.presence}
                      className="size-8"
                    />
                    <span className="min-w-0 truncate">
                      {getUserHandle(grant)}
                      <span className="ml-2 text-xs">{t("startHint")}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {current ? (
          // Keyed on the conversation: a thread holds a half-typed message, and
          // the one you were writing to Alice must not follow you to Bob.
          <Thread
            key={current.id}
            conversationId={current.id}
            otherUserId={current.other_user_id}
            name={nameOf(current.other_user_id)}
          />
        ) : withHandle ? (
          // Somebody was asked for. Either their thread is on its way, or there
          // is no channel and the panel says what would open one.
          failedFor === withHandle ? (
            <div className="flex flex-1 items-center justify-center p-8 text-center">
              <div className="max-w-sm space-y-3">
                <p className="text-muted-foreground text-sm">{t("openFailed")}</p>
                {/* A button rather than the effect having another go on its
                    own: the address has not changed, so nothing would re-run
                    it, and a state change that did would keep re-running it
                    against whatever is refusing. */}
                <Button
                  variant="outline"
                  onClick={() => targetId !== undefined && openWith(targetId, withHandle)}
                >
                  {t("tryAgain")}
                </Button>
              </div>
            </div>
          ) : target.isLoading || !conversationsLoaded || channelOpen ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <p className="text-muted-foreground text-sm">{t("loading")}</p>
            </div>
          ) : target.data ? (
            <StartWithPerson person={target.data} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-8">
              <StatusMessage
                icon={<UserX className="size-6" aria-hidden />}
                title={t("unknownAccount")}
              />
            </div>
          )
        ) : (
          <div className="flex flex-1 items-center justify-center p-8 text-center">
            <div className="max-w-sm space-y-2">
              <MessageSquare className="mx-auto size-8 text-muted-foreground" aria-hidden />
              <p className="font-medium">{t("empty.title")}</p>
              <p className="text-muted-foreground text-sm">{t("empty.body")}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Thread({
  conversationId,
  otherUserId,
  name,
}: {
  conversationId: string;
  otherUserId: number;
  name: string;
}) {
  const { t } = useTranslation("messages");
  const thread = useThread(conversationId);
  const send = useSendMessage(conversationId, otherUserId);
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement | null>(null);

  const messages = thread.data ?? [];
  // An open thread is a read thread — including whatever arrives while it is
  // open, which is why the count is what re-runs it.
  useMarkThreadRead(conversationId, messages.length);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="border-b px-6 py-3 font-medium text-sm">{name}</div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-6 py-4">
        {messages.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noHistoryHere")}</p>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={cn(
                "max-w-[70%] rounded-lg px-3 py-2 text-sm",
                message.mine ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"
              )}
            >
              {message.body}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>
      <form
        className="flex gap-2 border-t p-3"
        onSubmit={(event) => {
          event.preventDefault();
          const body = draft.trim();
          if (!body) return;
          setDraft("");
          // What was typed comes back if it could not be sent: the composer is
          // the only place it exists, and a failed send should not eat it.
          send.mutate(body, { onError: () => setDraft(body) });
        }}
      >
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("composerPlaceholder")}
          aria-label={t("composerPlaceholder")}
        />
        <Button type="submit" size="icon" disabled={send.isPending || !draft.trim()}>
          <Send className="size-4" aria-hidden />
          <span className="sr-only">{t("send")}</span>
        </Button>
      </form>
      {send.isError ? (
        <div className="px-3 pb-3">
          <p className="text-destructive text-sm">
            {send.error instanceof RecipientHasNoDeviceError
              ? t("recipientHasNoDevice", { name })
              : t("sendFailed")}
          </p>
        </div>
      ) : null}
    </section>
  );
}
