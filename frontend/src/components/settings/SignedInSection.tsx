/**
 * Where the account is signed in, as one list.
 *
 * Two credentials sit behind it. A browser holds a rotating session
 * (`auth_sessions`, named by what its user agent says it is); a phone that
 * signed in through the native app holds a device token (`user_tokens`, named
 * by the app). They are separate tables, separate endpoints and, for a while
 * yet, separate lifecycles — but to the person reading the page they are one
 * question, so they are one list here and the merge happens at this seam
 * rather than in an endpoint that would have to keep both shapes forever.
 *
 * The session doing the reading is marked rather than offered an end: signing
 * the current one out is what the sign-out button is, on every page.
 */
import { Monitor, MonitorSmartphone, Smartphone, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { type ClientKind, ClientKind as Kind } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import {
  useDeviceTokens,
  useMySessions,
  useRevokeDeviceToken,
  useRevokeOtherSessions,
  useRevokeSession,
} from "@/hooks/useSecurity";
import { toast } from "@/lib/chesterToast";
import { formatDateTime } from "@/lib/formatDate";

/** One row: a browser session or a signed-in phone, flattened to what is drawn. */
interface SignedInPlace {
  key: string;
  label: string;
  kind: ClientKind;
  ip: string | null;
  /** A session records its activity; a device token records only its issue. */
  lastActiveAt: string | null;
  startedAt: string;
  isCurrent: boolean;
  /** Most recent activity, for the ordering. */
  sortAt: number;
  end: () => void;
}

const KIND_ICONS = {
  [Kind.mobile]: Smartphone,
  [Kind.desktop]: Monitor,
  [Kind.unknown]: MonitorSmartphone,
} as const;

const SignedInRow = ({
  place,
  busy,
  onEnd,
}: {
  place: SignedInPlace;
  busy: boolean;
  onEnd: () => void;
}) => {
  const { t } = useTranslation("settings");
  const active = useRelativeTime(place.lastActiveAt);
  const Icon = KIND_ICONS[place.kind] ?? MonitorSmartphone;

  // A session says where it is and when it was last used; a phone has only the
  // moment it signed in, and says that rather than implying more.
  const detail = active
    ? [place.ip, t("security.activeAt", { when: active })].filter(Boolean).join(" · ")
    : t("security.loggedIn", { date: formatDateTime(place.startedAt) });

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="flex flex-wrap items-center gap-2 font-medium">
            {place.label}
            {place.isCurrent ? <Badge variant="secondary">{t("security.thisDevice")}</Badge> : null}
          </p>
          <p className="text-muted-foreground text-sm">{detail}</p>
        </div>
      </div>
      {place.isCurrent ? null : (
        <Button type="button" variant="outline" size="sm" onClick={onEnd} disabled={busy}>
          <Trash2 className="h-4 w-4" />
          {t("security.signOut")}
        </Button>
      )}
    </div>
  );
};

export const SignedInSection = () => {
  const { t } = useTranslation("settings");
  const [pendingEnd, setPendingEnd] = useState<SignedInPlace | null>(null);
  const [confirmSweep, setConfirmSweep] = useState(false);

  const sessionsQuery = useMySessions();
  const devicesQuery = useDeviceTokens();

  const revokeSession = useRevokeSession({
    onSuccess: () => toast.success(t("security.signedOutOne")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setPendingEnd(null),
  });
  const revokeDevice = useRevokeDeviceToken({
    onSuccess: () => toast.success(t("security.signedOutOne")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setPendingEnd(null),
  });
  const revokeOthers = useRevokeOtherSessions({
    onSuccess: () => toast.success(t("security.signedOutOthers")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setConfirmSweep(false),
  });

  const places = useMemo<SignedInPlace[]>(() => {
    const sessions = (sessionsQuery.data ?? []).map((row) => ({
      key: `session:${row.id}`,
      label: row.label ?? t("security.unknownDevice"),
      kind: row.kind,
      ip: row.ip,
      lastActiveAt: row.last_used_at ?? row.started_at,
      startedAt: row.started_at,
      isCurrent: row.is_current,
      sortAt: new Date(row.last_used_at ?? row.started_at).getTime(),
      end: () => revokeSession.mutate(row.id),
    }));

    const devices = (devicesQuery.data ?? []).map((device) => ({
      key: `device:${device.id}`,
      label: device.device_name ?? t("security.unknownDevice"),
      kind: Kind.mobile,
      ip: null,
      lastActiveAt: null,
      startedAt: device.created_at,
      isCurrent: false,
      sortAt: new Date(device.created_at).getTime(),
      end: () => revokeDevice.mutate(device.id),
    }));

    return [...sessions, ...devices].sort((a, b) => {
      if (a.isCurrent !== b.isCurrent) return a.isCurrent ? -1 : 1;
      return b.sortAt - a.sortAt;
    });
  }, [sessionsQuery.data, devicesQuery.data, revokeSession, revokeDevice, t]);

  const isLoading = sessionsQuery.isLoading || devicesQuery.isLoading;
  const isError = sessionsQuery.isError || devicesQuery.isError;
  const endable = places.filter((place) => !place.isCurrent);
  const ending = revokeSession.isPending || revokeDevice.isPending;

  return (
    <SettingsSection
      title={t("security.signedInTitle")}
      description={t("security.signedInDescription")}
    >
      {isLoading ? (
        <p className="text-muted-foreground text-sm">{t("security.loadingDevices")}</p>
      ) : isError ? (
        <p className="text-destructive text-sm">{t("security.devicesError")}</p>
      ) : places.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-6 text-center text-muted-foreground">
          <MonitorSmartphone className="h-10 w-10 opacity-50" />
          <div>
            <p className="font-medium">{t("security.noSignedIn")}</p>
            <p className="text-sm">{t("security.noSignedInHint")}</p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {places.map((place) => (
            <SignedInRow
              key={place.key}
              place={place}
              busy={ending}
              onEnd={() => setPendingEnd(place)}
            />
          ))}

          {endable.length > 0 ? (
            <div className="flex justify-end pt-1">
              <Button
                type="button"
                variant="outline"
                onClick={() => setConfirmSweep(true)}
                disabled={revokeOthers.isPending}
              >
                {t("security.signOutOthers")}
              </Button>
            </div>
          ) : null}
        </div>
      )}

      <AlertDialog open={pendingEnd !== null} onOpenChange={() => setPendingEnd(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("security.signOutDialogTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="security.signOutDialogDescription"
                ns="settings"
                values={{ deviceName: pendingEnd?.label ?? t("security.unknownDevice") }}
                components={{ bold: <span className="font-medium" /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("security.revokeDialogCancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={() => pendingEnd?.end()} disabled={ending}>
              {ending ? t("security.revoking") : t("security.signOutConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirmSweep} onOpenChange={() => setConfirmSweep(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("security.signOutOthersDialogTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("security.signOutOthersDialogDescription", { count: endable.length })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("security.revokeDialogCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => revokeOthers.mutate()}
              disabled={revokeOthers.isPending}
            >
              {revokeOthers.isPending ? t("security.revoking") : t("security.signOutOthersConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsSection>
  );
};
