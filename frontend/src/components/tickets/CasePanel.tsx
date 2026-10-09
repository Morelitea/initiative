/**
 * How an operations case was filed, on the task the team works it in.
 *
 * Who filed it and what they called it, and — where the case's stream holds a
 * conversation with them — that conversation and a way to answer it. It is
 * kept apart from the task's comments: everything here is what the requester
 * reads, and nothing in the thread below ever reaches them.
 */
import { Inbox, Send } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type CaseEvidenceRead,
  type CaseMessageRead,
  CommentAudience,
  Conversation,
} from "@/api/generated/initiativeAPI.schemas";
import { CommentContent } from "@/components/comments/CommentContent";
import { CaseHolds } from "@/components/tickets/CaseHolds";
import { communityEvidenceUrl, EvidenceList } from "@/components/tickets/Evidence";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { UserHoverLink } from "@/components/user/UserHoverLink";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCreateComment } from "@/hooks/useComments";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useUpdateTask } from "@/hooks/useTasks";
import { refreshTaskCase, useTaskCase } from "@/hooks/useTickets";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

interface CasePanelProps {
  taskId: number;
  /** Whether the reader may change the task. */
  canEdit: boolean;
}

const Message = ({
  message,
  evidence,
  urlFor,
}: {
  message: CaseMessageRead;
  evidence: CaseEvidenceRead[];
  urlFor: (evidenceId: number) => string;
}) => {
  const { t } = useTranslation("intake");
  const when = useRelativeTime(message.created_at);
  const name = message.author ? getUserDisplayName(message.author) : t("case.someone");
  return (
    <li className={cn("flex", message.from_requester ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[85%] rounded-lg border px-3 py-2",
          message.from_requester ? "bg-muted/40" : "border-primary/30 bg-primary/5"
        )}
      >
        <p className="mb-1 text-muted-foreground text-xs">
          {message.from_requester ? name : t("case.fromTeam", { name })} · {when}
        </p>
        <div className="text-sm">
          <CommentContent content={message.content} />
        </div>
        <EvidenceList className="mt-2" items={evidence} urlFor={urlFor} blurred />
      </div>
    </li>
  );
};

export const CasePanel = ({ taskId, canEdit }: CasePanelProps) => {
  const { t } = useTranslation(["intake", "common"]);
  const caseQuery = useTaskCase(taskId);
  const communityId = useActiveCommunityId();
  const [reply, setReply] = useState("");
  const createComment = useCreateComment();
  const updateTask = useUpdateTask();
  const filed = useRelativeTime(caseQuery.data?.opened_at ?? null);

  const found = caseQuery.data;
  if (!found) return null;

  const filerName = found.filer ? getUserDisplayName(found.filer) : null;
  const awaiting = found.awaiting_filer_status_id ?? null;
  const messages = found.messages ?? [];
  const teamHasSpoken = messages.some((message) => !message.from_requester);
  const pending = createComment.isPending || updateTask.isPending;
  const evidence = found.evidence ?? [];
  const shownIds = new Set(messages.map((message) => message.id));
  // Files beside no message shown here: carried in with a report, or sent
  // with words the conversation no longer holds.
  const loose = evidence.filter(
    (item) => item.comment_id == null || !shownIds.has(item.comment_id)
  );
  const urlFor = (evidenceId: number) => communityEvidenceUrl(communityId, evidenceId);

  const send = async (wait: boolean) => {
    const content = reply.trim();
    if (!content) return;
    await createComment.mutateAsync({
      content,
      task_id: taskId,
      audience: CommentAudience.filer,
    });
    setReply("");
    void refreshTaskCase(taskId);
    if (wait && awaiting != null) {
      await updateTask.mutateAsync({ taskId, data: { task_status_id: awaiting } });
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Inbox className="h-4 w-4" aria-hidden="true" />
          {t(`streams.${found.stream}.title`)}
        </CardTitle>
        <p className="text-muted-foreground text-sm">
          {filerName ? (
            <>
              {t("case.filedBy")}{" "}
              <UserHoverLink user={found.filer ?? null} className="font-medium text-foreground">
                {filerName}
              </UserHoverLink>
              {" · "}
            </>
          ) : (
            <>{t("case.noFiler")} · </>
          )}
          {filed}
        </p>
        {found.filer_subject ? (
          <p className="text-sm">
            <span className="text-muted-foreground">{t("case.theyCalledIt")}</span>{" "}
            {found.filer_subject}
          </p>
        ) : null}
      </CardHeader>
      {loose.length > 0 ? (
        <CardContent className="space-y-2 pb-3">
          <p className="font-medium text-muted-foreground text-xs">{t("evidence.heading")}</p>
          <EvidenceList items={loose} urlFor={urlFor} blurred />
        </CardContent>
      ) : null}
      {found.stream === "moderation" && found.subject_community_id != null ? (
        <CaseHolds
          taskId={taskId}
          communityId={found.subject_community_id}
          resourceType={found.resource_type}
          resourceId={found.resource_id}
        />
      ) : null}
      {found.filer && (
        <CardContent className="space-y-3">
          {messages.length > 0 ? (
            <ul className="space-y-3" aria-label={t("case.conversationLabel", { name: filerName })}>
              {messages.map((message) => (
                <Message
                  key={message.id}
                  message={message}
                  evidence={evidence.filter((item) => item.comment_id === message.id)}
                  urlFor={urlFor}
                />
              ))}
            </ul>
          ) : null}
          {found.conversation === Conversation.none ? (
            <p className="text-muted-foreground text-sm">{t("case.noConversation")}</p>
          ) : (
            <>
              {found.conversation === Conversation.staff_first && !teamHasSpoken ? (
                <p className="text-muted-foreground text-sm">{t("case.staffFirst")}</p>
              ) : null}
              <Textarea
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                placeholder={t("case.replyPlaceholder", { name: filerName })}
                aria-label={t("case.replyLabel", { name: filerName })}
                rows={3}
                disabled={!canEdit || pending}
              />
              <p className="text-muted-foreground text-xs">{t("case.replyHelp")}</p>
              <div className="flex flex-wrap justify-end gap-2">
                {awaiting != null ? (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!canEdit || pending || !reply.trim()}
                    onClick={() => void send(true)}
                  >
                    {t("case.replyAndWait")}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  disabled={!canEdit || pending || !reply.trim()}
                  onClick={() => void send(false)}
                >
                  <Send className="h-4 w-4" aria-hidden="true" />
                  {t("case.reply")}
                </Button>
              </div>
            </>
          )}
        </CardContent>
      )}
    </Card>
  );
};
