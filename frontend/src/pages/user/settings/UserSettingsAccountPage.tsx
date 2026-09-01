import { Capacitor } from "@capacitor/core";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { setAuthToken } from "@/api/client";
import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import { getUserHandle } from "@/lib/userDisplay";

interface UserSettingsAccountPageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

/**
 * The account: how you get in.
 *
 * Separate from Settings › Profile, which is the face other people see. The
 * split is along who the setting is for — nothing on this page is visible to
 * anyone else, and nothing on the profile page changes how you sign in. How
 * dates read to you is Settings › Interface, with the rest of that question.
 */
export const UserSettingsAccountPage = ({ user, refreshUser }: UserSettingsAccountPageProps) => {
  // Pull in ``auth`` and ``errors`` so the password-policy hint and the
  // server's ``PASSWORD_BREACHED`` code map without lazy-loading those
  // namespaces mid-submit.
  const { t } = useTranslation(["settings", "auth", "errors"]);
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [password, setPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  // Also editable beside the reminder time on Settings › Notifications, where
  // you need to see which clock the time is in.
  const [timezone, setTimezone] = useState(user.timezone ?? "UTC");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTimezone(user.timezone ?? "UTC");
  }, [user.timezone]);

  const updateAccount = useUpdateCurrentUser({
    onSuccess: async (_data, variables) => {
      // A password change rotates token_version server-side and re-sets the
      // session cookie. On web the stale in-memory bearer would otherwise still
      // be sent and 401 us out, so drop it and let the fresh cookie carry the
      // session. (Native uses bearer/device-token auth with no cookie fallback,
      // so it re-authenticates instead — left as-is.)
      if (variables.password && !Capacitor.isNativePlatform()) {
        setAuthToken(null);
      }
      setPassword("");
      setCurrentPassword("");
      setConfirmPassword("");
      setError(null);
      await refreshUser();
      toast.success(t("profile.updateSuccess"));
    },
    onError: (err: unknown) => {
      // Map server password-policy codes (``PASSWORD_TOO_SHORT``,
      // ``PASSWORD_BREACHED``) and other backend errors via the shared
      // helper; fall back to the generic update-error string.
      setError(getErrorMessage(err, "settings:profile.updateError"));
    },
  });

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (password && password !== confirmPassword) {
          setError(t("profile.passwordsMismatch"));
          return;
        }
        if (password && !user.has_federated_identity && !currentPassword) {
          setError(t("profile.currentPasswordRequired"));
          return;
        }
        if (password) {
          const policyError = validatePasswordLocal(password);
          if (policyError) {
            setError(policyError);
            return;
          }
        }
        const payload: Record<string, unknown> = {};
        if (fullName !== user.full_name) {
          payload.full_name = fullName;
        }
        if (timezone !== (user.timezone ?? "UTC")) {
          payload.timezone = timezone;
        }
        if (password) {
          payload.password = password;
          // Re-auth: the backend requires the current password to set a
          // new one (skipped for SSO-only accounts with no local password).
          if (!user.has_federated_identity) {
            payload.current_password = currentPassword;
          }
        }
        updateAccount.mutate(payload as UserSelfUpdate);
      }}
    >
      <SettingsSection
        title={t("account.identityTitle")}
        description={t("account.identityDescription")}
      >
        <div className="space-y-2">
          <Label>{t("profile.emailLabel")}</Label>
          <Input value={user.email} disabled readOnly />
          <p className="text-muted-foreground text-xs">{t("profile.emailHelp")}</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="full-name">{t("profile.fullNameLabel")}</Label>
          <Input
            id="full-name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder={t("profile.fullNamePlaceholder")}
          />
          <p className="text-muted-foreground text-xs">{t("account.fullNameHelp")}</p>
        </div>

        <div className="space-y-2">
          {/* Shown, not editable — the same arrangement the address has.
              It is how everyone else sees you, so it is the one thing on
              this page you would look for and not find. */}
          <Label>{t("profile.usernameLabel")}</Label>
          <Input value={getUserHandle(user)} disabled readOnly />
          <p className="text-muted-foreground text-xs">{t("profile.usernameHelp")}</p>
        </div>

        <div className="space-y-2">
          <Label>{t("profile.timezoneLabel")}</Label>
          <SearchableCombobox
            items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
            value={timezone}
            onValueChange={setTimezone}
            placeholder={t("profile.timezonePlaceholder")}
            emptyMessage={t("profile.timezoneEmpty")}
          />
          <p className="text-muted-foreground text-xs">{t("profile.timezoneHelp")}</p>
        </div>
      </SettingsSection>

      <SettingsSection
        title={t("account.passwordTitle")}
        description={t("account.passwordDescription")}
        footer={
          <>
            <Button type="submit" disabled={updateAccount.isPending}>
              {updateAccount.isPending ? t("profile.saving") : t("profile.saveChanges")}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={updateAccount.isPending}
              onClick={() => {
                setPassword("");
                setCurrentPassword("");
                setConfirmPassword("");
                setFullName(user.full_name ?? "");
                setTimezone(user.timezone ?? "UTC");
                setError(null);
              }}
            >
              {t("profile.reset")}
            </Button>
          </>
        }
      >
        {!user.has_federated_identity ? (
          <div className="space-y-2">
            <Label htmlFor="current-password">{t("profile.currentPasswordLabel")}</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              placeholder={t("profile.currentPasswordPlaceholder")}
            />
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="password">{t("profile.newPasswordLabel")}</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={t("profile.passwordPlaceholder")}
              minLength={password.length > 0 ? PASSWORD_MIN_LENGTH : undefined}
            />
            <p
              className={
                password.length > 0 && password.length < PASSWORD_MIN_LENGTH
                  ? "text-destructive text-xs"
                  : "text-muted-foreground text-xs"
              }
            >
              {t("auth:passwordPolicy.minLengthHelp")}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password">{t("profile.confirmPasswordLabel")}</Label>
            <Input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder={t("profile.passwordPlaceholder")}
            />
          </div>
        </div>

        {error ? <p className="text-destructive text-sm">{error}</p> : null}
      </SettingsSection>
    </form>
  );
};
