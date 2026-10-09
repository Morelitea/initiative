/**
 * One ticket the reader filed: where it stands, what has been said to them
 * about it, and — where the ticket takes it — their answer.
 *
 * The people handling it are shown as the team, never by name, and only what
 * was said to the reader is here; the team's own notes are not.
 */
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  Conversation,
  FilerState,
  type TicketMessageRead,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentContent } from "@/components/comments/CommentContent";
import { SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { EvidenceList, EvidencePicker, filedEvidenceUrl } from "@/components/tickets/Evidence";
import { TicketStateBadge } from "@/components/tickets/TicketStateBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useFiledTicket, useReplyToTicket } from "@/hooks/useTickets";
import { cn } from "@/lib/utils";

const Message = ({ message, taskId }: { message: TicketMessageRead; taskId: number }) => {
  const { t } = useTranslation("intake");
  const when = useRelativeTime(message.created_at);
  return (
    <li className={cn("flex", message.mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg border px-3 py-2",
          message.mine ? "border-primary/30 bg-primary/5" : "bg-muted/40"
        )}
      >
        <p className="mb-1 text-muted-foreground text-xs">
          {message.mine ? t("tickets.you") : t("tickets.team")} · {when}
        </p>
        <div className="text-sm">
          <CommentContent content={message.content} />
        </div>
        <EvidenceList
          className="mt-2"
          items={message.attachments ?? []}
          urlFor={(id) => filedEvidenceUrl(taskId, id)}
        />
      </div>
    </li>
  );
};

/** Why there is no box to answer in, where there is not one. */
const replyNote = (
  conversation: Conversation,
  state: FilerState
): "tickets.closedNote" | "tickets.noConversation" | "tickets.staffFirst" | null => {
  if (state === FilerState.closed) return "tickets.closedNote";
  if (conversation === Conversation.none) return "tickets.noConversation";
  if (conversation === Conversation.staff_first) return "tickets.staffFirst";
  return null;
};

export const TicketPage = () => {
  const { taskId: raw } = useParams({ strict: false }) as { taskId: string };
  // One ticket's draft is never another's: opening a different ticket on the
  // same route starts its page afresh.
  return <TicketView key={raw} taskId={Number(raw)} />;
};

const TicketView = ({ taskId }: { taskId: number }) => {
  const { t } = useTranslation(["intake", "common"]);
  const ticketQuery = useFiledTicket(taskId, { enabled: Number.isFinite(taskId) });
  const [reply, setReply] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const replyMutation = useReplyToTicket(taskId, {
    onSuccess: () => {
      setReply("");
      setFiles([]);
    },
  });
  const opened = useRelativeTime(ticketQuery.data?.opened_at ?? null);

  const ticket = ticketQuery.data;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6">
      <Button asChild variant="ghost" size="sm" className="-ml-2">
        <Link to="/my-tickets">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t("tickets.back")}
        </Link>
      </Button>

      {ticketQuery.isLoading ? (
        <SkeletonRegion>
          <Skeleton className="h-9 w-2/3" />
          <Skeleton className="h-40 w-full" />
        </SkeletonRegion>
      ) : !ticket ? (
        <p className="py-8 text-center text-muted-foreground text-sm">{t("tickets.notFound")}</p>
      ) : (
        <>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-semibold text-2xl tracking-tight">
                {ticket.subject || t(`streams.${ticket.stream}.title`)}
              </h1>
              <TicketStateBadge state={ticket.state} />
            </div>
            <p className="text-muted-foreground text-sm">
              {t(`streams.${ticket.stream}.title`)} · {t("tickets.opened", { when: opened })}
            </p>
            {ticket.state === FilerState.waiting_on_you ? (
              <p className="text-sm">{t("tickets.waitingNote")}</p>
            ) : null}
          </div>

          <ul className="space-y-3">
            {ticket.messages.map((message) => (
              <Message key={message.id} message={message} taskId={taskId} />
            ))}
          </ul>

          {ticket.can_reply ? (
            <Card>
              <CardContent className="space-y-3 pt-6">
                <Textarea
                  value={reply}
                  onChange={(event) => setReply(event.target.value)}
                  placeholder={t("tickets.replyPlaceholder")}
                  aria-label={t("tickets.replyLabel")}
                  rows={4}
                  disabled={replyMutation.isPending}
                />
                <EvidencePicker
                  policy={ticket.evidence}
                  files={files}
                  onChange={setFiles}
                  disabled={replyMutation.isPending}
                />
                <div className="flex justify-end">
                  <Button
                    type="button"
                    disabled={replyMutation.isPending || !reply.trim()}
                    onClick={() => replyMutation.mutate({ body: reply.trim(), files })}
                  >
                    {replyMutation.isPending ? t("tickets.sending") : t("tickets.send")}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ) : (
            (() => {
              const note = replyNote(ticket.conversation, ticket.state);
              return note ? <p className="text-muted-foreground text-sm">{t(note)}</p> : null;
            })()
          )}
        </>
      )}
    </div>
  );
};
