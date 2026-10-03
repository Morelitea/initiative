import { useState } from "react";
import { useTranslation } from "react-i18next";

import { CommunityStatus } from "@/api/generated/initiativeAPI.schemas";
import { ContactDialog } from "@/components/tickets/ContactDialog";
import { FileTicketDialog } from "@/components/tickets/FileTicketDialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useBillingPortal } from "@/hooks/useBillingPortal";
import { useGuildPaymentIssue } from "@/hooks/useGuildPaymentIssue";
import type { GuildEntry } from "@/hooks/useGuilds";
import { useTicketAvailability } from "@/hooks/useTickets";
import { getSessionItem, setSessionItem } from "@/lib/storage";

const SEEN_KEY_PREFIX = "guild-status-notice:";

const seenThisSession = (key: string): boolean => getSessionItem(SEEN_KEY_PREFIX + key) !== null;

const markSeenThisSession = (key: string) => setSessionItem(SEEN_KEY_PREFIX + key, "1");

export const guildStatusNoticeApplies = (guild: GuildEntry): boolean =>
  guild.accessType !== "grant" && guild.can.seat && guild.status === CommunityStatus.read_only;

type Stage = "notice" | "help" | "closed";

export const GuildStatusNotice = ({ guild }: { guild: GuildEntry }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const { billing, canSell, openPortal } = useBillingPortal();
  const seenKey = `${guild.id}:${guild.status}`;
  const [stage, setStage] = useState<Stage>(() =>
    guildStatusNoticeApplies(guild) && !seenThisSession(seenKey) ? "notice" : "closed"
  );

  const noticeOpen = stage === "notice";
  const askBilling = noticeOpen && Boolean(billing);
  const issue = useGuildPaymentIssue(guild.id, { enabled: askBilling });
  const paymentFailed = askBilling && issue.data?.payment_failed === true;

  const askSupport = noticeOpen && (!askBilling || issue.isFetched) && !paymentFailed;
  const support = useTicketAvailability(guild.id, {
    enabled: askSupport || stage === "help",
    retry: false,
  });
  const offered = support.data?.support;
  // A form where the deployment takes help requests from here; otherwise the
  // address it gave, which is still somebody to ask.
  const contact = offered?.mode === "email" ? offered.contact : null;
  const canAskForHelp = askSupport && (offered?.mode === "form" || contact != null);

  if (stage === "closed") return null;

  if (stage === "help") {
    const close = (open: boolean) => !open && setStage("closed");
    return contact ? (
      <ContactDialog open onOpenChange={close} contact={contact} />
    ) : (
      <FileTicketDialog
        open
        onOpenChange={close}
        ticket={{ stream: "support" }}
        guildId={guild.id}
      />
    );
  }

  if ((askBilling && issue.isPending) || (askSupport && support.isPending)) return null;

  const dismiss = () => {
    markSeenThisSession(seenKey);
    setStage("closed");
  };

  return (
    <AlertDialog open onOpenChange={(open) => !open && dismiss()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {paymentFailed
              ? t("statusNotice.paymentTitle", { name: guild.name })
              : t("statusNotice.title")}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {paymentFailed
              ? canSell
                ? t("statusNotice.paymentDescription")
                : t("statusNotice.paymentDescriptionInApp")
              : t("statusNotice.description")}
          </AlertDialogDescription>
          <AlertDialogDescription>{t("statusNotice.readOnly")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {paymentFailed && canSell ? (
            <>
              <AlertDialogCancel onClick={dismiss}>{t("statusNotice.notNow")}</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  markSeenThisSession(seenKey);
                  void openPortal(guild.id, "manage");
                }}
              >
                {t("statusNotice.updatePayment")}
              </AlertDialogAction>
            </>
          ) : canAskForHelp ? (
            <>
              <AlertDialogCancel onClick={dismiss}>{t("common:ok")}</AlertDialogCancel>
              <AlertDialogAction
                onClick={(event) => {
                  event.preventDefault();
                  markSeenThisSession(seenKey);
                  setStage("help");
                }}
              >
                {t("statusNotice.contactSupport")}
              </AlertDialogAction>
            </>
          ) : (
            <AlertDialogAction onClick={dismiss}>{t("common:ok")}</AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
};
