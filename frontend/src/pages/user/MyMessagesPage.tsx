import { MessageSquare, Send, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { StatusMessage } from "@/components/StatusMessage";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ratchetSupported } from "@/crypto/client";
import { useMessageRequests } from "@/hooks/useDirectMessages";
import {
  useCollectMessages,
  useConversations,
  useDmDevice,
  useSendMessage,
  useStartConversation,
  useThread,
} from "@/hooks/useMyMessages";
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
 */
export function MyMessagesPage() {
  const { t } = useTranslation("messages");
  const device = useDmDevice();
  const conversations = useConversations();
  const requests = useMessageRequests();
  const startConversation = useStartConversation();
  const [selected, setSelected] = useState<string | null>(null);

  useCollectMessages(device.isSuccess);

  /** Everyone with an accepted channel, whether or not it has been opened. */
  const reachable = useMemo(() => requests.data?.accepted ?? [], [requests.data?.accepted]);
  const nameFor = useMemo(() => {
    const names = new Map<number, string>();
    for (const grant of reachable) {
      names.set(grant.user_id, `${grant.username}#${grant.discriminator}`);
    }
    return names;
  }, [reachable]);

  const rows = conversations.data?.conversations ?? [];
  const current = rows.find((row) => row.id === selected) ?? null;

  // Somebody you may message but have not opened a channel with yet.
  const unopened = reachable.filter(
    (grant) => !rows.some((row) => row.other_user_id === grant.user_id)
  );

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
              {rows.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(row.id)}
                    className={cn(
                      "w-full px-4 py-3 text-left text-sm hover:bg-accent",
                      row.id === selected && "bg-accent"
                    )}
                  >
                    {nameFor.get(row.other_user_id) ?? t("unknownAccount")}
                  </button>
                </li>
              ))}
              {unopened.map((grant) => (
                <li key={grant.user_id}>
                  <button
                    type="button"
                    disabled={startConversation.isPending}
                    onClick={() =>
                      startConversation.mutate(grant.user_id, {
                        onSuccess: (conversation) => setSelected(conversation.id),
                      })
                    }
                    className="w-full px-4 py-3 text-left text-muted-foreground text-sm hover:bg-accent"
                  >
                    {grant.username}#{grant.discriminator}
                    <span className="ml-2 text-xs">{t("startHint")}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {current ? (
          <Thread
            conversationId={current.id}
            otherUserId={current.other_user_id}
            name={nameFor.get(current.other_user_id) ?? t("unknownAccount")}
          />
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
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, []);

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
          send.mutate(body);
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
          <p className="text-destructive text-sm">{t("sendFailed")}</p>
        </div>
      ) : null}
    </section>
  );
}
