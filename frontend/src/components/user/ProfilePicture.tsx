import { Camera } from "lucide-react";
import { type ChangeEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  ProfileDecorationsOutput,
  UserSelfUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import {
  deleteMyAvatarApiV1UsersMeAvatarDelete,
  uploadMyAvatarApiV1UsersMeAvatarPut,
} from "@/api/generated/users/users";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tabs, TabsBar, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { ImageRenditionError, renderAvatar } from "@/lib/imageRenditions";
import type { AvatarSourceUser, DisplayableUser } from "@/lib/userDisplay";

/** Where this server serves an uploaded picture from. A linked one — from a
 *  single sign-on account — is any other URL. */
const UPLOADED_PREFIX = "/api/v1/users/";

const uploaded = (url: string | null | undefined): string | null =>
  url?.startsWith(UPLOADED_PREFIX) ? url : null;

const linked = (url: string | null | undefined): boolean => Boolean(url) && !uploaded(url);

interface ProfilePictureProps {
  user: DisplayableUser & AvatarSourceUser;
  decorations: ProfileDecorationsOutput;
  online?: boolean;
  className?: string;
  /** Whether this is your own picture, and clicking it opens the editor. */
  editable?: boolean;
  onChanged?: () => Promise<void> | void;
}

/**
 * The picture, and — on your own profile — the way to change it.
 *
 * Clicking the face is how everyone expects to change the face, so there is no
 * separate section for it: the control is the thing it controls. Uploading
 * writes immediately, because an uploaded picture is a resource of its own
 * rather than a field of a form; a linked URL is the only part with anything
 * to save.
 */
export const ProfilePicture = ({
  user,
  decorations,
  online,
  className,
  editable = false,
  onChanged,
}: ProfilePictureProps) => {
  const { t } = useTranslation(["settings", "common"]);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"upload" | "url">(linked(user.avatar_url) ? "url" : "upload");
  const [url, setUrl] = useState(linked(user.avatar_url) ? (user.avatar_url ?? "") : "");
  const [busy, setBusy] = useState(false);

  const saveLink = useUpdateCurrentUser({
    onSuccess: async () => {
      setOpen(false);
      await onChanged?.();
    },
    onError: (error: unknown) =>
      toast.error(getErrorMessage(error, "settings:profile.updateError")),
  });

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await work();
      setOpen(false);
      await onChanged?.();
    } catch (error) {
      console.error(error);
      // A picture the browser could not make sense of never reached the
      // server, so it has its own message rather than an API code.
      toast.error(
        error instanceof ImageRenditionError
          ? t(`settings:profile.avatar.${error.code}`)
          : getErrorMessage(error, "settings:profile.avatar.failed")
      );
    } finally {
      setBusy(false);
    }
  };

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    void run(async () => uploadMyAvatarApiV1UsersMeAvatarPut({ file: await renderAvatar(file) }));
  };

  const avatar = (
    <ProfileAvatar
      user={user}
      decorations={decorations}
      online={online}
      ring
      className={className}
    />
  );

  if (!editable) return avatar;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="group relative rounded-full focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
          aria-label={t("settings:profile.avatarLabel")}
        >
          {avatar}
          {/* Only on hover and focus: a camera badge sitting on every avatar
              all the time would read as part of the picture. */}
          <span className="absolute inset-0 flex items-center justify-center rounded-full bg-black/45 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            <Camera className="size-6 text-white" aria-hidden="true" />
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <p className="font-medium text-sm">{t("settings:profile.avatarLabel")}</p>
        <Tabs value={mode} onValueChange={(value) => setMode(value as "upload" | "url")}>
          <TabsBar>
            <TabsTrigger value="upload">{t("settings:profile.avatarUploadTab")}</TabsTrigger>
            <TabsTrigger value="url">{t("settings:profile.avatarUrlTab")}</TabsTrigger>
          </TabsBar>
          <TabsContent value="upload" className="space-y-2">
            <Input type="file" accept="image/*" disabled={busy} onChange={pick} />
            <p className="text-muted-foreground text-xs">
              {t("settings:profile.avatarUploadHelp")}
            </p>
            {uploaded(user.avatar_url) ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void run(() => deleteMyAvatarApiV1UsersMeAvatarDelete())}
              >
                {t("settings:profile.removeUploadedAvatar")}
              </Button>
            ) : null}
          </TabsContent>
          <TabsContent value="url" className="space-y-2">
            <Input
              type="url"
              placeholder={t("settings:profile.avatarUrlPlaceholder")}
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
            <Button
              type="button"
              size="sm"
              disabled={saveLink.isPending}
              onClick={() => saveLink.mutate({ avatar_url: url || null } as UserSelfUpdate)}
            >
              {saveLink.isPending ? t("common:submitting") : t("settings:profile.saveChanges")}
            </Button>
          </TabsContent>
        </Tabs>
      </PopoverContent>
    </Popover>
  );
};
