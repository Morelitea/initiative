import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useAnswerHistoryRequest, useHistoryRequest } from "@/hooks/useMyMessages";

/**
 * Another of your devices, asking to be sent the messages it cannot derive.
 *
 * Signing in as somebody is enough to receive their new messages and
 * deliberately not enough to receive their old ones, so this is the one thing
 * standing between an account and its past. It shows the asking device's
 * fingerprint rather than only its name: a name is whatever a browser reported,
 * and the number is what the other screen is showing at the same moment.
 */
export const HistoryRequestPanel = () => {
  const { t } = useTranslation("messages");
  const request = useHistoryRequest();
  const answer = useAnswerHistoryRequest();

  if (!request.data) return null;

  return (
    <section className="space-y-3 border-b bg-muted/40 px-6 py-4">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="space-y-1">
          <h2 className="font-medium text-sm">{t("historyRequest.title")}</h2>
          <p className="max-w-prose text-muted-foreground text-sm">
            {t("historyRequest.body", {
              device: request.data.label ?? t("historyRequest.unknownDevice"),
            })}
          </p>
          <p className="font-mono text-xs tracking-wider">{request.data.fingerprint}</p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2 pl-6">
        <Button
          type="button"
          size="sm"
          disabled={answer.isPending}
          onClick={() => answer.mutate(true)}
        >
          {t("historyRequest.approve")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={answer.isPending}
          onClick={() => answer.mutate(false)}
        >
          {t("historyRequest.decline")}
        </Button>
      </div>
    </section>
  );
};
