import { ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SafetyCode } from "@/components/messages/SafetyCode";
import { Button } from "@/components/ui/button";
import { useAcknowledgePeerKeyChange, usePeerKeyChanges } from "@/hooks/useMyMessages";

/**
 * A conversation partner's device key changed under a thread already in use.
 *
 * The directory is the server's, so the honest thing to say is that this
 * browser cannot tell which of two things happened: they replaced a device, or
 * somebody with the database enrolled one. The wording says both, in that
 * order, because the first is far more common and a notice that only names the
 * attack gets read as an error.
 *
 * The new code is drawn so it can be compared out of band -- the same
 * comparison the history panels ask for, reused here because it is the same
 * question. Dismissing records that the interruption was read, which is not
 * the same as approving; the key was already in use by the time this appeared.
 */
export const PeerKeyChangeNotice = () => {
  const { t } = useTranslation("messages");
  const changes = usePeerKeyChanges();
  const acknowledge = useAcknowledgePeerKeyChange();

  const change = changes.data?.[0];
  if (!change) return null;

  return (
    <section
      className="space-y-3 border-destructive/40 border-b bg-destructive/5 px-6 py-4"
      // Announced on arrival: it appears because a send happened, not because
      // the person navigated here, so nothing else would read it out.
      role="alert"
    >
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
        <div className="space-y-3">
          <div className="space-y-1">
            <h2 className="font-medium text-sm">{t("peerKeyChange.title")}</h2>
            <p className="max-w-prose text-muted-foreground text-sm">{t("peerKeyChange.body")}</p>
          </div>
          <SafetyCode fingerprint={change.now} />
          <Button
            size="sm"
            variant="outline"
            onClick={() => acknowledge.mutate(change.deviceId)}
            disabled={acknowledge.isPending}
          >
            {t("peerKeyChange.acknowledge")}
          </Button>
        </div>
      </div>
    </section>
  );
};
