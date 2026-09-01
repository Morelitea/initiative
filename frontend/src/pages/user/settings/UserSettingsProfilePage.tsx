import { Link } from "@tanstack/react-router";
import { type ChangeEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import {
  deleteMyAvatarApiV1UsersMeAvatarDelete,
  uploadMyAvatarApiV1UsersMeAvatarPut,
} from "@/api/generated/users/users";
import { EmojiPicker } from "@/components/EmojiPicker";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { BadgePicker, SlotPicker } from "@/components/user/DecorationPicker";
import { MyDecorationPacks } from "@/components/user/MyDecorationPacks";
import { ProfileCard } from "@/components/user/ProfileCard";
import { useMyDecorations, useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { ImageRenditionError, renderAvatar } from "@/lib/imageRenditions";

/** Where this server serves an uploaded picture from. A linked one — from a
 *  single sign-on account — is any other URL. */
const UPLOADED_PREFIX = "/api/v1/users/";

const uploadedAvatar = (user: UserRead): string | null =>
  user.avatar_url?.startsWith(UPLOADED_PREFIX) ? user.avatar_url : null;

const isLinked = (user: UserRead): boolean => Boolean(user.avatar_url) && !uploadedAvatar(user);

/** Mirrors ``STATUS_TEXT_MAX_LENGTH`` on the server. */
const STATUS_MAX_LENGTH = 100;

/** Mirrors ``MAX_PROFILE_BADGES`` on the server. */
const MAX_BADGES = 6;

interface UserSettingsProfilePageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

/**
 * Your profile: the face other people see, and everything that makes it.
 *
 * The picture, what you are up to, and what you are wearing all live here
 * because they are one thing to the reader of your profile — and the card at
 * the top is that reader's view, kept live against the drafts below it, so
 * nothing on this page has to be imagined.
 *
 * How you sign in is Settings › Account. Nothing on this page is private.
 */
export const UserSettingsProfilePage = ({ user, refreshUser }: UserSettingsProfilePageProps) => {
  const { t } = useTranslation(["settings", "profiles", "common"]);
  const { data: library } = useMyDecorations();

  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [avatarMode, setAvatarMode] = useState<"upload" | "url">(isLinked(user) ? "url" : "upload");
  // Only the *linked* URL is edited in this form. An uploaded picture is its
  // own resource, written the moment it is picked, so it has no draft state.
  const [avatarUrl, setAvatarUrl] = useState(isLinked(user) ? (user.avatar_url ?? "") : "");
  const [avatarBusy, setAvatarBusy] = useState(false);
  // What you're up to, in your own words — an emoji, a line, or both.
  const [statusEmoji, setStatusEmoji] = useState(user.custom_status.emoji ?? null);
  const [statusText, setStatusText] = useState(user.custom_status.text ?? "");
  const [error, setError] = useState<string | null>(null);

  const [banner, setBanner] = useState(user.profile_decorations.banner ?? null);
  const [frame, setFrame] = useState(user.profile_decorations.frame ?? null);
  const [badges, setBadges] = useState<string[]>(user.profile_decorations.badges ?? []);

  // Each half of this page follows the saved values it mirrors, and only those.
  // Both halves used to re-sync on any change to `user`, which meant saving one
  // of them threw away whatever was picked and not yet saved in the other.
  const savedSelf = JSON.stringify([user.full_name, user.avatar_url, user.custom_status]);
  const [syncedSelf, setSyncedSelf] = useState(savedSelf);
  if (syncedSelf !== savedSelf) {
    setSyncedSelf(savedSelf);
    setFullName(user.full_name ?? "");
    setAvatarUrl(isLinked(user) ? (user.avatar_url ?? "") : "");
    setAvatarMode(isLinked(user) ? "url" : "upload");
    setStatusEmoji(user.custom_status.emoji ?? null);
    setStatusText(user.custom_status.text ?? "");
  }

  // Removing a pack takes its pieces off server-side, so the look has to follow
  // when it changes underneath the form — but, again, only then.
  const savedLook = JSON.stringify(user.profile_decorations);
  const [syncedLook, setSyncedLook] = useState(savedLook);
  if (syncedLook !== savedLook) {
    setSyncedLook(savedLook);
    setBanner(user.profile_decorations.banner ?? null);
    setFrame(user.profile_decorations.frame ?? null);
    setBadges(user.profile_decorations.badges ?? []);
  }

  const avatarPreview = useMemo(() => {
    if (avatarMode === "url") {
      return avatarUrl || null;
    }
    return uploadedAvatar(user);
  }, [avatarMode, avatarUrl, user]);

  const saveAppearance = useUpdateCurrentUser({
    onSuccess: async () => {
      setError(null);
      await refreshUser();
      toast.success(t("settings:profile.updateSuccess"));
    },
    onError: (err: unknown) => setError(getErrorMessage(err, "settings:profile.updateError")),
  });

  const saveLook = useUpdateCurrentUser({
    onSuccess: async () => {
      await refreshUser();
      toast.success(t("profiles:look.saved"));
    },
    onError: (err: unknown) => toast.error(getErrorMessage(err, "profiles:look.failed")),
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

  const saved = user.profile_decorations;
  const lookChanged =
    banner !== (saved.banner ?? null) ||
    frame !== (saved.frame ?? null) ||
    badges.join() !== (saved.badges ?? []).join();

  return (
    <div className="space-y-6">
      {/* Your profile as everyone else sees it, wearing the drafts below rather
          than what is saved — the point of a preview is the change you have not
          committed to yet. You are looking at the app, so the presence dot is
          the truth and not a mock-up of one. */}
      <ProfileCard
        user={{ ...user, full_name: fullName, avatar_url: avatarPreview }}
        decorations={{ banner, frame, badges }}
        status={{ emoji: statusEmoji, text: statusText || null }}
        online
        joinedAt={user.created_at}
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          const payload: Record<string, unknown> = {};
          if (fullName !== user.full_name) {
            payload.full_name = fullName;
          }
          // The uploaded picture is written on pick, so this form only
          // carries the linked one. Clearing the field on the URL tab is
          // how a linked picture is removed.
          if (avatarMode === "url") {
            payload.avatar_url = avatarUrl || null;
          }
          if (
            statusEmoji !== (user.custom_status.emoji ?? null) ||
            statusText !== (user.custom_status.text ?? "")
          ) {
            // One column, so the emoji and the line go together — and an
            // emptied field is the status taken off, not an empty line.
            payload.custom_status = { emoji: statusEmoji, text: statusText || null };
          }
          saveAppearance.mutate(payload as UserSelfUpdate);
        }}
      >
        <SettingsSection
          title={t("settings:profile.cardTitle")}
          description={t("settings:profile.cardDescription")}
          contentClassName="space-y-6"
          footer={
            <>
              <Button type="submit" disabled={saveAppearance.isPending}>
                {saveAppearance.isPending
                  ? t("settings:profile.saving")
                  : t("settings:profile.saveChanges")}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={saveAppearance.isPending}
                onClick={() => {
                  setFullName(user.full_name ?? "");
                  setAvatarUrl(isLinked(user) ? (user.avatar_url ?? "") : "");
                  setAvatarMode(isLinked(user) ? "url" : "upload");
                  setStatusEmoji(user.custom_status.emoji ?? null);
                  setStatusText(user.custom_status.text ?? "");
                  setError(null);
                }}
              >
                {t("settings:profile.reset")}
              </Button>
            </>
          }
        >
          <div className="space-y-2">
            <Label htmlFor="full-name">{t("settings:profile.fullNameLabel")}</Label>
            <Input
              id="full-name"
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder={t("settings:profile.fullNamePlaceholder")}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="status-text">{t("settings:profile.statusLabel")}</Label>
            <div className="flex gap-2">
              <div className="w-32 shrink-0">
                <EmojiPicker
                  id="status-emoji"
                  value={statusEmoji}
                  onChange={setStatusEmoji}
                  placeholder={t("settings:profile.statusEmojiPlaceholder")}
                />
              </div>
              <Input
                id="status-text"
                value={statusText}
                onChange={(event) => setStatusText(event.target.value)}
                placeholder={t("settings:profile.statusPlaceholder")}
                maxLength={STATUS_MAX_LENGTH}
              />
            </div>
            <p className="text-muted-foreground text-xs">{t("settings:profile.statusHelp")}</p>
          </div>

          <div className="space-y-3">
            <Label>{t("settings:profile.avatarLabel")}</Label>
            <Tabs
              value={avatarMode}
              onValueChange={(value) => setAvatarMode(value as "upload" | "url")}
            >
              <TabsBar>
                <TabsTrigger value="upload">{t("settings:profile.avatarUploadTab")}</TabsTrigger>
                <TabsTrigger value="url">{t("settings:profile.avatarUrlTab")}</TabsTrigger>
              </TabsBar>
              <TabsContent value="upload" className="space-y-2">
                <Input
                  type="file"
                  accept="image/*"
                  disabled={avatarBusy}
                  onChange={handleAvatarUpload}
                />
                <p className="text-muted-foreground text-xs">
                  {t("settings:profile.avatarUploadHelp")}
                </p>
                {uploadedAvatar(user) ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={avatarBusy}
                    onClick={handleAvatarRemove}
                  >
                    {t("settings:profile.removeUploadedAvatar")}
                  </Button>
                ) : null}
              </TabsContent>
              <TabsContent value="url" className="space-y-2">
                <Input
                  type="url"
                  placeholder={t("settings:profile.avatarUrlPlaceholder")}
                  value={avatarUrl}
                  onChange={(event) => setAvatarUrl(event.target.value)}
                />
                {avatarUrl ? (
                  <Button type="button" variant="ghost" size="sm" onClick={() => setAvatarUrl("")}>
                    {t("settings:profile.clearAvatarUrl")}
                  </Button>
                ) : null}
              </TabsContent>
            </Tabs>
          </div>

          {error ? <p className="text-destructive text-sm">{error}</p> : null}
        </SettingsSection>
      </form>

      <SettingsSection
        title={t("profiles:myPacks.title")}
        description={t("profiles:myPacks.description")}
        action={
          <Button variant="outline" size="sm" asChild>
            <Link to="/marketplace">{t("profiles:myPacks.browse")}</Link>
          </Button>
        }
      >
        <MyDecorationPacks />
      </SettingsSection>

      <SettingsSection
        title={t("profiles:look.title")}
        description={t("profiles:look.description")}
        contentClassName="space-y-6"
        footer={
          <Button
            disabled={!lookChanged || saveLook.isPending}
            onClick={() =>
              saveLook.mutate({ profile_decorations: { banner, frame, badges } } as UserSelfUpdate)
            }
          >
            {saveLook.isPending ? t("common:submitting") : t("profiles:look.save")}
          </Button>
        }
      >
        <div className="space-y-2">
          <Label className="text-muted-foreground text-xs">
            {t("profiles:decorationPicker.banner")}
          </Label>
          <SlotPicker kind="banner" value={banner} onChange={setBanner} owned={library?.items} />
        </div>
        <div className="space-y-2">
          <Label className="text-muted-foreground text-xs">
            {t("profiles:decorationPicker.frame")}
          </Label>
          <SlotPicker kind="frame" value={frame} onChange={setFrame} owned={library?.items} />
        </div>
        <div className="space-y-2">
          <Label className="text-muted-foreground text-xs">
            {t("profiles:decorationPicker.badge")}
          </Label>
          <BadgePicker
            value={badges}
            onChange={setBadges}
            owned={library?.items}
            max={MAX_BADGES}
          />
        </div>
      </SettingsSection>
    </div>
  );
};
