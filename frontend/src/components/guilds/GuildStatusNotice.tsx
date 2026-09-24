import { useState } from "react";
import { useTranslation } from "react-i18next";

import { GuildStatus } from "@/api/generated/initiativeAPI.schemas";
import { AskForHelpDialog } from "@/components/support/AskForHelpDialog";
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
import { useSupportAvailability } from "@/hooks/useSupport";
import { holdsGuildSeat } from "@/lib/permissions";

const SEEN_KEY_PREFIX = "guild-status-notice:";

const seenThisSession = (key: string): boolean => {
  try {
    return window.sessionStorage.getItem(SEEN_KEY_PREFIX + key) !== null;
  } catch {
    return false;
  }
};

const markSeenThisSession = (key: string) => {
  try {
    window.sessionStorage.setItem(SEEN_KEY_PREFIX + key, "1");
  } catch {
    // Storage unavailable; the notice shows again next time.
  }
};

export const guildStatusNoticeApplies = (guild: GuildEntry): boolean =>
  guild.accessType !== "grant" && holdsGuildSeat(guild) && guild.status === GuildStatus.read_only;

type Stage = "notice" | "help" | "closed";

export const GuildStatusNotice = ({ guild }: { guild: GuildEntry }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const { billing, openPortal } = useBillingPortal();
  const seenKey = `${guild.id}:${guild.status}`;
  const [stage, setStage] = useState<Stage>(() =>
    guildStatusNoticeApplies(guild) && !seenThisSession(seenKey) ? "notice" : "closed"
  );

  const noticeOpen = stage === "notice";
  const askBilling = noticeOpen && Boolean(billing);
  const issue = useGuildPaymentIssue(guild.id, { enabled: askBilling });
  const paymentFailed = askBilling && issue.data?.payment_failed === true;

  const askSupport = noticeOpen && (!askBilling || issue.isFetched) && !paymentFailed;
  const support = useSupportAvailability(guild.id, { enabled: askSupport, retry: false });
  const canAskForHelp = askSupport && support.data?.available === true;

  if (stage === "closed") return null;

  if (stage === "help") {
    return (
      <AskForHelpDialog
        open
        onOpenChange={(open) => !open && setStage("closed")}
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
            {paymentFailed ? t("statusNotice.paymentDescription") : t("statusNotice.description")}
          </AlertDialogDescription>
          <AlertDialogDescription>{t("statusNotice.readOnly")}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          {paymentFailed ? (
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
