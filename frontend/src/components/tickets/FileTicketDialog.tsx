/**
 * Filing a ticket: asking for help, or reporting something.
 *
 * One dialog for every kind, opened by whatever surface files one — the
 * sidebar's "Ask for help", a Report flag, a status notice. Each kind brings
 * its own fields; sending, the acknowledgement and the fallback are shared.
 *
 * What comes back is an acknowledgement and nothing else. A report in
 * particular never says where it went, whether somebody had already reported
 * the same thing, or what happens next: a report is not a conversation with
 * the person who sent it.
 *
 * Where a report has to go to the people who run the deployment and they have
 * set nothing up to receive it, the dialog turns into their address, if they
 * gave one, rather than ending on a refusal.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ReportReason } from "@/api/generated/initiativeAPI.schemas";
import { ReportReason as Reason } from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  FAQ_URL,
  type TicketCreate,
  useFileTicket,
  useTicketAvailability,
} from "@/hooks/useTickets";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";

/** Match the columns behind them, so a field stops where the server would. */
const SUBJECT_MAX = 200;
const BODY_MAX = 5000;
const DETAIL_MAX = 4000;

/** The reasons, in the order they are offered. */
const REASONS: ReportReason[] = [
  Reason.harassment,
  Reason.hate,
  Reason.violence,
  Reason.sexual_content,
  Reason.self_harm,
  Reason.illegal,
  Reason.spam,
  Reason.misinformation,
  Reason.other,
];

/** What is being filed. */
export type TicketKind =
  | { stream: "support" }
  | {
      stream: "moderation";
      /** A `SearchEntityType` or a `PlatformReportTarget` value. */
      targetType: string;
      targetId: number;
    };

export interface FileTicketDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  ticket: TicketKind;
  /** The community the reader is standing in, when they are in one. Asking
   *  for help is always from one; a report may come from nowhere. */
  guildId: number | null;
}

export const FileTicketDialog = ({
  open,
  onOpenChange,
  ticket,
  guildId,
}: FileTicketDialogProps) => {
  const { t } = useTranslation(["intake", "moderation", "common"]);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState<ReportReason | "">("");
  // Set, to what the server said, when the people who run the deployment had
  // nowhere to receive this. Kept apart from their address, which may still
  // be on its way: the dialog turns into the address whenever it arrives, and
  // says why it could not send only where there is no address at all.
  const [nowhere, setNowhere] = useState<string | null>(null);
  const availability = useTicketAvailability(guildId, { enabled: open });
  const contact = availability.data?.[ticket.stream].contact ?? null;

  const isReport = ticket.stream === "moderation";

  const file = useFileTicket({
    onSuccess: () => {
      toast.success(isReport ? t("moderation:report.thanks") : t("help.thanks"));
      onOpenChange(false);
      setSubject("");
      setBody("");
      setReason("");
    },
    onError: (err) => {
      const message = getErrorMessage(
        err,
        isReport ? "moderation:report.error" : "intake:help.error"
      );
      if (getHttpStatus(err) === 503) {
        setNowhere(message);
        return;
      }
      toast.error(message);
    },
  });

  if (nowhere && contact) {
    // What they wrote goes with them, so falling back to email does not mean
    // writing it again.
    const draft =
      ticket.stream === "moderation"
        ? {
            subject: reason
              ? `${t("moderation:report.title")}: ${t(`moderation:reasons.${reason}`)}`
              : t("moderation:report.title"),
            body: [body.trim(), `${ticket.targetType} ${ticket.targetId}`]
              .filter(Boolean)
              .join("\n\n"),
          }
        : { subject: subject.trim(), body: body.trim() };
    return (
      <ContactDialog open={open} onOpenChange={onOpenChange} contact={contact} draft={draft} />
    );
  }

  const payload = (): TicketCreate | null => {
    if (ticket.stream === "moderation") {
      if (!reason) return null;
      return {
        stream: "moderation",
        target_type: ticket.targetType,
        target_id: ticket.targetId,
        reason,
        detail: body.trim() || null,
        community_id: guildId,
      };
    }
    if (guildId == null || !subject.trim() || !body.trim()) return null;
    return { stream: "support", community_id: guildId, subject: subject.trim(), body: body.trim() };
  };
  const ready = payload();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isReport ? t("moderation:report.title") : t("help.title")}</DialogTitle>
          <DialogDescription>
            {isReport ? t("moderation:report.description") : t("help.description")}
          </DialogDescription>
        </DialogHeader>

        {isReport ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ticket-reason">{t("moderation:report.reasonLabel")}</Label>
              <Select value={reason} onValueChange={(v) => setReason(v as ReportReason)}>
                <SelectTrigger id="ticket-reason">
                  <SelectValue placeholder={t("moderation:report.reasonPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {REASONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t(`moderation:reasons.${value}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="ticket-detail">{t("moderation:report.detailLabel")}</Label>
              <Textarea
                id="ticket-detail"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={t("moderation:report.detailPlaceholder")}
                rows={4}
                maxLength={DETAIL_MAX}
              />
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ticket-subject">{t("help.subjectLabel")}</Label>
              <Input
                id="ticket-subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder={t("help.subjectPlaceholder")}
                maxLength={SUBJECT_MAX}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ticket-body">{t("help.bodyLabel")}</Label>
              <Textarea
                id="ticket-body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={t("help.bodyPlaceholder")}
                rows={6}
                maxLength={BODY_MAX}
              />
            </div>
            {/* The FAQ is still the faster answer for most of what gets asked,
                so it stays one click away from the form. */}
            <p className="text-muted-foreground text-xs">
              <a
                href={FAQ_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-foreground"
              >
                {t("help.browseFaq")}
              </a>
            </p>
          </div>
        )}

        {nowhere && !availability.isPending && (
          <p className="text-destructive text-sm" role="alert">
            {nowhere}
          </p>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button disabled={!ready || file.isPending} onClick={() => ready && file.mutate(ready)}>
            {isReport ? t("moderation:report.submit") : t("help.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
