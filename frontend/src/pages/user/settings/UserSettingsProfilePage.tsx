import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { BadgePicker, SlotPicker } from "@/components/user/DecorationPicker";
import { MyDecorationPacks } from "@/components/user/MyDecorationPacks";
import { ProfilePreview } from "@/components/user/ProfilePreview";
import { useMyDecorations, useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/** Mirrors ``MAX_PROFILE_BADGES`` on the server. */
const MAX_BADGES = 6;

interface UserSettingsProfilePageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

/**
 * Your profile: the face other people see, and everything that makes it.
 *
 * The card at the top is that face, kept live against the pickers below it —
 * and it is the controls too. Your picture and your status are both set by
 * clicking them on the card, because that is where you are looking when you
 * decide to change them, and a form further down would be a second place to
 * keep in agreement with the first.
 *
 * Your packs sit under your look rather than over it: what you are wearing is
 * why you came, and what you own is where you go to change it.
 *
 * How you sign in — and the real name that communities showing real names use
 * — is Settings › Account. Nothing on this page is private.
 */
export const UserSettingsProfilePage = ({ user, refreshUser }: UserSettingsProfilePageProps) => {
  const { t } = useTranslation(["profiles", "common"]);
  const { data: library } = useMyDecorations();

  const [banner, setBanner] = useState(user.profile_decorations.banner ?? null);
  const [frame, setFrame] = useState(user.profile_decorations.frame ?? null);
  const [badges, setBadges] = useState<string[]>(user.profile_decorations.badges ?? []);

  // Removing a pack takes its pieces off server-side, so the pickers follow the
  // saved look when it changes underneath them — but only then. Following the
  // whole account would throw away a pick every time anything else was saved.
  const savedLook = JSON.stringify(user.profile_decorations);
  const [syncedLook, setSyncedLook] = useState(savedLook);
  if (syncedLook !== savedLook) {
    setSyncedLook(savedLook);
    setBanner(user.profile_decorations.banner ?? null);
    setFrame(user.profile_decorations.frame ?? null);
    setBadges(user.profile_decorations.badges ?? []);
  }

  const saveLook = useUpdateCurrentUser({
    onSuccess: async () => {
      await refreshUser();
      toast.success(t("profiles:look.saved"));
    },
    onError: (error: unknown) => toast.error(getErrorMessage(error, "profiles:look.failed")),
  });

  const saved = user.profile_decorations;
  const changed =
    banner !== (saved.banner ?? null) ||
    frame !== (saved.frame ?? null) ||
    badges.join() !== (saved.badges ?? []).join();

  return (
    <div className="space-y-6">
      <ProfilePreview
        user={user}
        decorations={{ banner, frame, badges }}
        status={user.custom_status}
        joinedAt={user.created_at}
        onChanged={refreshUser}
      />

      <SettingsSection
        title={t("profiles:look.title")}
        description={t("profiles:look.description")}
        contentClassName="space-y-6"
        footer={
          <Button
            disabled={!changed || saveLook.isPending}
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
    </div>
  );
};
