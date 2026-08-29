import { Capacitor } from "@capacitor/core";
import { type ChangeEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { setAuthToken } from "@/api/client";
import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import {
  deleteMyAvatarApiV1UsersMeAvatarDelete,
  uploadMyAvatarApiV1UsersMeAvatarPut,
} from "@/api/generated/users/users";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { ImageRenditionError, renderAvatar } from "@/lib/imageRenditions";
import { getInitials } from "@/lib/initials";
import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "@/lib/passwordPolicy";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getUserDisplayName } from "@/lib/userDisplay";

/** Where this server serves an uploaded picture from. A linked one — from a
 *  single sign-on account — is any other URL. */
const UPLOADED_PREFIX = "/api/v1/users/";

const uploadedAvatar = (user: UserRead): string | null =>
  user.avatar_url?.startsWith(UPLOADED_PREFIX) ? user.avatar_url : null;

const isLinked = (user: UserRead): boolean => Boolean(user.avatar_url) && !uploadedAvatar(user);

interface UserSettingsProfilePageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

export const UserSettingsProfilePage = ({ user, refreshUser }: UserSettingsProfilePageProps) => {
  // Pull in ``auth`` and ``errors`` so the password-policy hint and the
  // server's ``PASSWORD_BREACHED`` code map without lazy-loading those
  // namespaces mid-submit.
  const { t } = useTranslation(["settings", "auth", "errors"]);
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [password, setPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [avatarMode, setAvatarMode] = useState<"upload" | "url">(isLinked(user) ? "url" : "upload");
  // Only the *linked* URL is edited in this form. An uploaded picture is its
  // own resource, written the moment it is picked, so it has no draft state.
  const [avatarUrl, setAvatarUrl] = useState(isLinked(user) ? (user.avatar_url ?? "") : "");
  const [avatarBusy, setAvatarBusy] = useState(false);
  // The same field is also editable on Settings → Notifications (the
  // overdue-reminder time uses it). Surfacing it here too means a new
  // user can fix a wrong default during their first profile pass
  // without having to discover the notifications tab.
  const [timezone, setTimezone] = useState(user.timezone ?? "UTC");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setFullName(user.full_name ?? "");
    setAvatarUrl(isLinked(user) ? (user.avatar_url ?? "") : "");
    setAvatarMode(isLinked(user) ? "url" : "upload");
    setTimezone(user.timezone ?? "UTC");
  }, [user]);

  const avatarPreview = useMemo(() => {
    if (avatarMode === "url") {
      return avatarUrl || "";
    }
    return resolveUploadUrl(uploadedAvatar(user)) ?? "";
  }, [avatarMode, avatarUrl, user]);

  const updateProfile = useUpdateCurrentUser({
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

  /** Write the picture straight away — it is a resource of its own, not a
   *  field of this form, so there is nothing to save alongside it. */
  const runAvatar = async (work: () => Promise<unknown>) => {
    setAvatarBusy(true);
    try {
      await work();
      await refreshUser();
    } catch (err) {
      console.error(err);
      // A picture the browser could not make sense of never reached the
      // server, so it has its own message rather than an API code.
      toast.error(
        err instanceof ImageRenditionError
          ? t(`settings:profile.avatar.${err.code}`)
          : getErrorMessage(err, "settings:profile.avatar.failed")
      );
    } finally {
      setAvatarBusy(false);
    }
  };

  const handleAvatarUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setAvatarMode("upload");
    void runAvatar(async () =>
      uploadMyAvatarApiV1UsersMeAvatarPut({ file: await renderAvatar(file) })
    );
  };

  const handleAvatarRemove = () => void runAvatar(() => deleteMyAvatarApiV1UsersMeAvatarDelete());

  const initials = getInitials(user.full_name, user.email);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Avatar className="h-16 w-16">
          {avatarPreview ? <AvatarImage src={avatarPreview} alt={fullName || user.email} /> : null}
          <AvatarFallback userId={user.id}>{initials}</AvatarFallback>
        </Avatar>
        <div>
          <p className="font-semibold text-lg">{getUserDisplayName(user)}</p>
          <p className="text-muted-foreground text-sm">{t("profile.subtitle")}</p>
        </div>
      </div>
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("profile.cardTitle")}</CardTitle>
          <CardDescription>{t("profile.cardDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
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
              if (password) {
                payload.password = password;
                // Re-auth: the backend requires the current password to set a
                // new one (skipped for SSO-only accounts with no local password).
                if (!user.has_federated_identity) {
                  payload.current_password = currentPassword;
                }
              }
              // The uploaded picture is written on pick, so this form only
              // carries the linked one. Clearing the field on the URL tab is
              // how a linked picture is removed.
              if (avatarMode === "url") {
                payload.avatar_url = avatarUrl || null;
              }
              if (timezone !== (user.timezone ?? "UTC")) {
                payload.timezone = timezone;
              }
              updateProfile.mutate(payload as UserSelfUpdate);
            }}
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
            </div>

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

            <div className="space-y-3">
              <Label>{t("profile.avatarLabel")}</Label>
              <Tabs
                value={avatarMode}
                onValueChange={(value) => setAvatarMode(value as "upload" | "url")}
              >
                <TabsBar>
                  <TabsTrigger value="upload">{t("profile.avatarUploadTab")}</TabsTrigger>
                  <TabsTrigger value="url">{t("profile.avatarUrlTab")}</TabsTrigger>
                </TabsBar>
                <TabsContent value="upload" className="space-y-2">
                  <Input
                    type="file"
                    accept="image/*"
                    disabled={avatarBusy}
                    onChange={handleAvatarUpload}
                  />
                  <p className="text-muted-foreground text-xs">{t("profile.avatarUploadHelp")}</p>
                  {uploadedAvatar(user) ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={avatarBusy}
                      onClick={handleAvatarRemove}
                    >
                      {t("profile.removeUploadedAvatar")}
                    </Button>
                  ) : null}
                </TabsContent>
                <TabsContent value="url" className="space-y-2">
                  <Input
                    type="url"
                    placeholder={t("profile.avatarUrlPlaceholder")}
                    value={avatarUrl}
                    onChange={(event) => setAvatarUrl(event.target.value)}
                  />
                  {avatarUrl ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setAvatarUrl("")}
                    >
                      {t("profile.clearAvatarUrl")}
                    </Button>
                  ) : null}
                </TabsContent>
              </Tabs>
            </div>

            {error ? <p className="text-destructive text-sm">{error}</p> : null}

            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={updateProfile.isPending}>
                {updateProfile.isPending ? t("profile.saving") : t("profile.saveChanges")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={updateProfile.isPending}
                onClick={() => {
                  setFullName(user.full_name ?? "");
                  setPassword("");
                  setCurrentPassword("");
                  setConfirmPassword("");
                  setAvatarUrl(isLinked(user) ? (user.avatar_url ?? "") : "");
                  setAvatarMode(isLinked(user) ? "url" : "upload");
                  setTimezone(user.timezone ?? "UTC");
                  setError(null);
                }}
              >
                {t("profile.reset")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};
