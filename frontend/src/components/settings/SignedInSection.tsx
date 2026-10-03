/**
 * Where the account is signed in.
 *
 * Every place is a session (`auth_sessions`): a browser names itself by what
 * its user agent says it is, and the app by the name it signed in with.
 *
 * The session doing the reading is marked rather than offered an end: signing
 * the current one out is what the sign-out button is, on every page.
 */
import { Monitor, MonitorSmartphone, Smartphone, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import {
  ClientKind as Kind,
  type SignedInSessionInfo,
} from "@/api/generated/initiativeAPI.schemas";
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
import { useMySessions, useRevokeOtherSessions, useRevokeSession } from "@/hooks/useSecurity";
import { toast } from "@/lib/chesterToast";

const KIND_ICONS = {
  [Kind.mobile]: Smartphone,
  [Kind.desktop]: Monitor,
  [Kind.unknown]: MonitorSmartphone,
} as const;

/** When a session was last used, or when it began if it has not been since. */
const lastActiveAt = (session: SignedInSessionInfo) => session.last_used_at ?? session.started_at;

const SignedInRow = ({
  session,
  busy,
  onEnd,
}: {
  session: SignedInSessionInfo;
  busy: boolean;
  onEnd: () => void;
}) => {
  const { t } = useTranslation("settings");
  const active = useRelativeTime(lastActiveAt(session));
  const Icon = KIND_ICONS[session.kind] ?? MonitorSmartphone;
  const detail = [session.ip, t("security.activeAt", { when: active })].filter(Boolean).join(" · ");

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="flex flex-wrap items-center gap-2 font-medium">
            {session.label ?? t("security.unknownDevice")}
            {session.is_current ? (
              <Badge variant="secondary">{t("security.thisDevice")}</Badge>
            ) : null}
          </p>
          <p className="text-muted-foreground text-sm">{detail}</p>
        </div>
      </div>
      {session.is_current ? null : (
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
  const [pendingEnd, setPendingEnd] = useState<SignedInSessionInfo | null>(null);
  const [confirmSweep, setConfirmSweep] = useState(false);

  const sessionsQuery = useMySessions();

  const revokeSession = useRevokeSession({
    onSuccess: () => toast.success(t("security.signedOutOne")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setPendingEnd(null),
  });
  const revokeOthers = useRevokeOtherSessions({
    onSuccess: () => toast.success(t("security.signedOutOthers")),
    onError: () => toast.error(t("security.revokeError")),
    onSettled: () => setConfirmSweep(false),
  });

  // The current session first, then the most recently active.
  const sessions = useMemo(
    () =>
      [...(sessionsQuery.data ?? [])].sort((a, b) => {
        if (a.is_current !== b.is_current) return a.is_current ? -1 : 1;
        return new Date(lastActiveAt(b)).getTime() - new Date(lastActiveAt(a)).getTime();
      }),
    [sessionsQuery.data]
  );

  const endable = sessions.filter((session) => !session.is_current);

  return (
    <SettingsSection
      title={t("security.signedInTitle")}
      description={t("security.signedInDescription")}
    >
      {sessionsQuery.isLoading ? (
        <p className="text-muted-foreground text-sm">{t("security.loadingDevices")}</p>
      ) : sessionsQuery.isError ? (
        <p className="text-destructive text-sm">{t("security.devicesError")}</p>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-6 text-center text-muted-foreground">
          <MonitorSmartphone className="h-10 w-10 opacity-50" />
          <div>
            <p className="font-medium">{t("security.noSignedIn")}</p>
            <p className="text-sm">{t("security.noSignedInHint")}</p>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {sessions.map((session) => (
            <SignedInRow
              key={session.id}
              session={session}
              busy={revokeSession.isPending}
              onEnd={() => setPendingEnd(session)}
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
            <AlertDialogAction
              onClick={() => pendingEnd && revokeSession.mutate(pendingEnd.id)}
              disabled={revokeSession.isPending}
            >
              {revokeSession.isPending ? t("security.revoking") : t("security.signOutConfirm")}
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
