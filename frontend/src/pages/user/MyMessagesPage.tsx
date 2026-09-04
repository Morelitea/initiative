import { useSearch } from "@tanstack/react-router";
import { Check, CheckCheck, Send, ShieldCheck, UserX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProfileDecorationsOutput } from "@/api/generated/initiativeAPI.schemas";
import { ConversationList } from "@/components/messages/ConversationList";
import { MessageContent } from "@/components/messages/MessageContent";
import { StartWithPerson } from "@/components/messages/StartWithPerson";
import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { RelativeTime } from "@/components/ui/relative-time";
import { Textarea } from "@/components/ui/textarea";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { ratchetSupported } from "@/crypto/client";
import { RecipientHasNoDeviceError } from "@/crypto/messaging";
import type { ReceiptState, StoredMessage } from "@/crypto/store";
import { useAuth } from "@/hooks/useAuth";
import { useMessageRequests } from "@/hooks/useDirectMessages";
import {
  useCollectMessages,
  useConversations,
  useDmDevice,
  useMarkThreadRead,
  useSendMessage,
  useStartConversation,
  useThread,
} from "@/hooks/useMyMessages";
import { useUserProfile } from "@/hooks/useUsers";
import { getUserHandle } from "@/lib/userDisplay";
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
  // The whole grant rather than a name: the thread draws a person, and
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
    // Fills the shell: `main` has a real height now, so the thread can be what
    // is left of it after the header, and its log is the only thing that
    // scrolls.
    <div className="flex h-full min-h-0 flex-col gap-4">
      <header className="space-y-1">
        <h1 className="font-semibold text-2xl">{t("title")}</h1>
        <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
          <ShieldCheck className="size-3.5 shrink-0" aria-hidden />
          {t("encryptedNotice")}
        </p>
      </header>

      {/* Who there is to talk to lives in the sidebar, which drills into this
          route -- so the page is only ever the one conversation. That is what
          leaves a phone the whole width for it. */}
      {current ? (
        // Keyed on the conversation: a thread holds a half-typed message, and
        // the one you were writing to Alice must not follow you to Bob.
        <Thread
          key={current.id}
          conversationId={current.id}
          otherUserId={current.other_user_id}
          name={nameOf(current.other_user_id)}
          them={personFor.get(current.other_user_id)}
        />
      ) : withHandle ? (
        // Somebody was asked for. Either their thread is on its way, or there
        // is no channel and the panel says what would open one.
        failedFor === withHandle ? (
          <div className="space-y-3 text-center">
            <p className="text-muted-foreground text-sm">{t("openFailed")}</p>
            {/* A button rather than the effect having another go on its own:
                the address has not changed, so nothing would re-run it, and a
                state change that did would keep re-running it against whatever
                is refusing. */}
            <Button
              variant="outline"
              onClick={() => targetId !== undefined && openWith(targetId, withHandle)}
            >
              {t("tryAgain")}
            </Button>
          </div>
        ) : target.isLoading || !conversationsLoaded || channelOpen ? (
          <p className="text-muted-foreground text-sm">{t("loading")}</p>
        ) : target.data ? (
          <StartWithPerson person={target.data} />
        ) : (
          <StatusMessage
            icon={<UserX className="size-6" aria-hidden />}
            title={t("unknownAccount")}
          />
        )
      ) : (
        // The list, not a note about where the list is. On a phone the sidebar
        // shuts on the way here, so this is the only thing on screen -- and on
        // a wide screen it is a landing view rather than an empty one.
        <section className="rounded-lg border">
          <h2 className="border-b px-3 py-2 font-medium text-sm">{t("empty.title")}</h2>
          <div className="p-2">
            <ConversationList />
          </div>
        </section>
      )}
    </div>
  );
}

/**
 * How long a quiet gap has to be before the next message starts a new run.
 *
 * A run is one person speaking once. Same sender is not enough on its own --
 * two messages a day apart are two occasions, and drawing them as one leaves
 * the second wearing the first one's timestamp.
 */
const RUN_GAP_MS = 5 * 60 * 1000;

/** Whether the second message carries on the first one's run. */
const continuesRun = (before: StoredMessage, after: StoredMessage) => {
  if (before.mine !== after.mine) return false;
  const gap = new Date(after.at).getTime() - new Date(before.at).getTime();
  // An unreadable time groups by sender alone rather than breaking every run.
  return Number.isNaN(gap) || gap < RUN_GAP_MS;
};

/**
 * How far one of your own messages has got, at the end of the run it is in.
 *
 * One tick means a device of theirs holds it; two mean somebody looked. Nothing
 * back yet draws no tick at all -- the message being on screen is already the
 * whole of what this side knows, since one that never reached them is refused
 * rather than shown. An account that has switched receipts off therefore never
 * draws a tick, which reads the same as somebody who has not opened the app,
 * and is the point of that switch.
 */
const Receipt = ({ state }: { state?: ReceiptState }) => {
  const { t } = useTranslation("messages");
  const label = t(`receipt.${state ?? "sent"}`);
  return (
    <span className={cn("relative flex items-center", state === "read" && "text-primary")}>
      {/* Said either way: an absent tick is a state, not an absent one. */}
      <span className="sr-only">{label}</span>
      {state === "read" ? (
        <CheckCheck className="size-3.5" aria-hidden />
      ) : state === "delivered" ? (
        <Check className="size-3.5" aria-hidden />
      ) : null}
    </span>
  );
};

/** A person as the thread needs to draw them: a picture and a colour. */
type Speaker =
  | {
      user_id?: number;
      id?: number;
      username?: string | null;
      discriminator?: number | null;
      avatar_url?: string | null;
      profile_decorations?: ProfileDecorationsOutput | null;
    }
  | null
  | undefined;

/**
 * One side's picture, drawn once per run of their messages.
 *
 * Smaller on a narrow screen, where the width it costs is width the message
 * does not get.
 */
const SPEAKER_SIZE = "size-6 sm:size-8";

const Speaking = ({ who, hidden }: { who: Speaker; hidden: boolean }) =>
  hidden || !who ? (
    // The space is held either way, so a run's messages stay in one column
    // rather than stepping sideways under the first of them.
    <div className={cn(SPEAKER_SIZE, "shrink-0")} aria-hidden />
  ) : (
    <ProfileAvatar
      user={{ ...who, id: who.id ?? who.user_id }}
      decorations={who.profile_decorations}
      className={SPEAKER_SIZE}
    />
  );

function Thread({
  conversationId,
  otherUserId,
  name,
  them,
}: {
  conversationId: string;
  otherUserId: number;
  name: string;
  /** The other side, for their picture. Absent while the grant is still loading. */
  them: Speaker;
}) {
  const { t } = useTranslation("messages");
  const { user: me } = useAuth();
  const thread = useThread(conversationId);
  const send = useSendMessage(conversationId, otherUserId);
  const [draft, setDraft] = useState("");
  const log = useRef<HTMLDivElement | null>(null);
  const composer = useRef<HTMLTextAreaElement | null>(null);

  // The composer is as tall as what is in it, up to the cap the CSS sets --
  // measured rather than counted, so a long line that wrapped takes the room
  // it actually needs. Reset first: scrollHeight cannot shrink on its own.
  //
  // The borders are added back because the box is sized border-box and
  // scrollHeight is not: one line set to exactly its own scrollHeight is two
  // pixels short of itself, which is enough to scroll an empty composer.
  useEffect(() => {
    const field = composer.current;
    if (!field) return;
    field.style.height = "auto";
    const borders = field.offsetHeight - field.clientHeight;
    field.style.height = `${field.scrollHeight + borders}px`;
  }, [draft]);

  const messages = thread.data ?? [];
  // An open thread is a read thread — including whatever arrives while it is
  // open, which is why the count is what re-runs it.
  useMarkThreadRead(conversationId, messages.length, otherUserId);
  useEffect(() => {
    // The log's own scrollTop, not `scrollIntoView`. That asks the browser to
    // bring an element into view by scrolling *every* scrollport it sits in --
    // including ones with `overflow: hidden`, which are still scrollable to a
    // script even though nothing offers the reader a way back. The only box
    // that should move here is this one.
    const element = log.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages.length]);

  const submit = () => {
    const body = draft.trim();
    if (!body || send.isPending) return;
    setDraft("");
    // What was typed comes back if it could not be sent: the composer is the
    // only place it exists, and a failed send should not eat it.
    send.mutate(body, { onError: () => setDraft(body) });
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border">
      <div className="shrink-0 border-b px-3 py-2 font-medium text-sm">{name}</div>
      <div
        ref={log}
        // Reaching the end of the thread stops there rather than handing the
        // rest of the gesture to whatever is behind it.
        className="min-h-0 flex-1 space-y-1 overflow-y-auto overscroll-contain p-3"
      >
        {messages.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noHistoryHere")}</p>
        ) : (
          messages.map((message, index) => {
            // One picture per run rather than per message: a picture beside
            // every line of somebody talking is the same fact six times, and
            // the run is what the eye reads as one person speaking.
            const startsRun = index === 0 || !continuesRun(messages[index - 1], message);
            // The time goes under the last of a run, for the same reason: it
            // is when they finished saying it.
            const endsRun =
              index === messages.length - 1 || !continuesRun(message, messages[index + 1]);
            return (
              <div
                key={message.id}
                className={cn(
                  // Aligned to the top of the bubble: a picture beside the last
                  // line of a long message reads as belonging to whatever comes
                  // after it rather than to what it is under.
                  "flex items-start gap-2",
                  message.mine && "flex-row-reverse",
                  startsRun && index > 0 && "pt-2"
                )}
              >
                <Speaking who={message.mine ? me : them} hidden={!startsRun} />
                <div
                  className={cn(
                    "flex min-w-0 max-w-[75%] flex-col gap-0.5",
                    message.mine && "items-end"
                  )}
                >
                  <div
                    className={cn(
                      "rounded-lg px-3 py-2 text-sm",
                      // `wrap-anywhere` rather than `break-words`: only this
                      // one counts towards how narrow the bubble may be, so a
                      // single unbroken run of characters wraps instead of
                      // sizing the bubble to itself and running off the side.
                      "wrap-anywhere w-fit max-w-full",
                      message.mine ? "bg-primary text-primary-foreground" : "bg-muted"
                    )}
                  >
                    <MessageContent body={message.body} />
                  </div>
                  {endsRun ? (
                    <span className="flex items-center gap-1 px-1 text-muted-foreground text-xs">
                      <RelativeTime date={message.at} />
                      {message.mine ? <Receipt state={message.receipt} /> : null}
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })
        )}
      </div>
      <form
        className="flex shrink-0 items-end gap-2 border-t p-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Textarea
          ref={composer}
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          // Enter sends, because that is what a composer this shape is for;
          // Shift+Enter is the newline, and the field grows to show it.
          onKeyDown={(event) => {
            if (event.key !== "Enter" || event.shiftKey) return;
            event.preventDefault();
            submit();
          }}
          placeholder={t("composerPlaceholder")}
          aria-label={t("composerPlaceholder")}
          // No scrollbar chrome: the field grows instead of scrolling until it
          // reaches the cap, and past that the caret is what moves the view.
          className="max-h-40 min-h-0 resize-none overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        />
        <Button
          type="submit"
          size="icon"
          className="shrink-0"
          disabled={send.isPending || !draft.trim()}
        >
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
