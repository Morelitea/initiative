/**
 * What an app has asked to do as you, one line per purpose, and your answer.
 *
 * An app asks for one purpose at a time — "comment on the linked issue as the
 * person who closed it" — in its own words, which is why the label is shown
 * quoted and attributed to the app rather than as Initiative's. Each line is
 * answered on its own: allow reading, allow reading and changes (only when the
 * app asked for that much), decline, and later withdraw. The app-wide request,
 * if the app made one, comes first.
 *
 * Every answer is the viewer's own. Nothing here names or answers for anybody
 * else.
 */

import { useTranslation } from "react-i18next";

import {
  ConsentAccess,
  ConsentStatus,
  type GuildAppConsentRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useGrantAppConsent, useRevokeAppConsent } from "@/hooks/useGuildAppDetail";
import { useInitiatives } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export interface AppConsentRequestsProps {
  appId: number;
  appName: string;
  consents: GuildAppConsentRead[];
}

export function AppConsentRequests({ appId, appName, consents }: AppConsentRequestsProps) {
  const { t } = useTranslation(["apps", "common"]);
  const grant = useGrantAppConsent(appId);
  const revoke = useRevokeAppConsent(appId);
  const initiatives = useInitiatives({ enabled: consents.some((c) => c.initiative_id) });
  const busy = grant.isPending || revoke.isPending;

  const initiativeName = (id: number) =>
    initiatives.data?.find((initiative) => initiative.id === id)?.name ?? null;

  const allow = async (consent: GuildAppConsentRead, access: ConsentAccess) => {
    try {
      await grant.mutateAsync({ consentId: consent.id, access });
      toast.success(t("apps:consent.allowed", { name: appName }));
    } catch (error) {
      toast.error(getErrorMessage(error, "apps:consent.failed"));
    }
  };

  const end = async (consent: GuildAppConsentRead) => {
    const declining = consent.status === ConsentStatus.pending;
    try {
      await revoke.mutateAsync(consent.id);
      toast.success(
        declining
          ? t("apps:consent.declinedToast", { name: appName })
          : t("apps:consent.withdrawnToast", { name: appName })
      );
    } catch (error) {
      toast.error(getErrorMessage(error, "apps:consent.failed"));
    }
  };

  return (
    <div className="space-y-2">
      <h4 className="font-medium text-sm">{t("apps:consent.title")}</h4>
      <p className="text-muted-foreground text-xs">
        {t("apps:consent.description", { name: appName })}
      </p>
      <ul className="space-y-2">
        {consents.map((consent) => {
          const askedForChanges = consent.requested_access === ConsentAccess.read_write;
          const granted = consent.status === ConsentStatus.granted;
          const where =
            consent.initiative_id != null ? initiativeName(consent.initiative_id) : null;
          return (
            <li key={consent.id} className="space-y-2 rounded-md border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 space-y-0.5">
                  <p className="break-words text-sm">
                    {t("apps:consent.inTheirWords", { name: appName, label: consent.label })}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {[
                      consent.purpose == null ? t("apps:consent.appWide") : null,
                      consent.initiative_id == null
                        ? t("apps:consent.anywhere")
                        : where
                          ? t("apps:consent.inInitiative", { initiative: where })
                          : t("apps:consent.inOneInitiative"),
                      askedForChanges
                        ? t("apps:consent.askedReadWrite")
                        : t("apps:consent.askedRead"),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <Badge variant={granted ? "secondary" : "outline"}>{t(statusKey(consent))}</Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                {!(granted && consent.granted_access === ConsentAccess.read) && (
                  <Button
                    size="sm"
                    variant={granted ? "outline" : "default"}
                    disabled={busy}
                    onClick={() => allow(consent, ConsentAccess.read)}
                  >
                    {granted ? t("apps:consent.readOnly") : t("apps:consent.allowRead")}
                  </Button>
                )}
                {askedForChanges &&
                  !(granted && consent.granted_access === ConsentAccess.read_write) && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy}
                      onClick={() => allow(consent, ConsentAccess.read_write)}
                    >
                      {t("apps:consent.allowReadWrite")}
                    </Button>
                  )}
                {(granted || consent.status === ConsentStatus.pending) && (
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => end(consent)}>
                    {granted ? t("apps:consent.withdraw") : t("apps:consent.decline")}
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function statusKey(consent: GuildAppConsentRead) {
  switch (consent.status) {
    case ConsentStatus.granted:
      return consent.granted_access === ConsentAccess.read_write
        ? "apps:consent.statusReadWrite"
        : "apps:consent.statusRead";
    case ConsentStatus.declined:
      return "apps:consent.statusDeclined";
    case ConsentStatus.revoked:
      return "apps:consent.statusRevoked";
    default:
      return "apps:consent.statusPending";
  }
}
