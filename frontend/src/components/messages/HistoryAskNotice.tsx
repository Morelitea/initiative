import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SafetyCode } from "@/components/messages/SafetyCode";
import { useHistoryAsk } from "@/hooks/useMyMessages";

/**
 * This device, waiting to be sent the messages it arrived without.
 *
 * The other half of the comparison. The device being asked about shows the
 * code the deciding screen is showing, so whoever is holding both is checking
 * two things against each other rather than being told a number and trusting
 * it. It says nothing about how long that will take, because nothing here
 * knows: the other device has to be opened by a person before it can answer.
 */
export const HistoryAskNotice = () => {
  const { t } = useTranslation("messages");
  const ask = useHistoryAsk();

  if (!ask.data) return null;

  return (
    <section className="space-y-3 border-b bg-muted/40 px-6 py-4">
      <div className="flex items-start gap-2">
        <KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
        <div className="space-y-3">
          <div className="space-y-1">
            <h2 className="font-medium text-sm">{t("historyAsk.title")}</h2>
            <p className="max-w-prose text-muted-foreground text-sm">{t("historyAsk.body")}</p>
          </div>
          <SafetyCode fingerprint={ask.data.fingerprint} />
        </div>
      </div>
    </section>
  );
};
