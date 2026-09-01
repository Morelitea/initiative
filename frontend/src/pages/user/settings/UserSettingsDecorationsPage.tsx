import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { BadgePicker, SlotPicker } from "@/components/user/DecorationPicker";
import { MyDecorationPacks } from "@/components/user/MyDecorationPacks";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useMyDecorations, useUpdateCurrentUser } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { resolveDecoration } from "@/lib/profileDecorations";

/** Mirrors ``MAX_PROFILE_BADGES`` on the server. */
const MAX_BADGES = 6;

interface UserSettingsDecorationsPageProps {
  user: UserRead;
  refreshUser: () => Promise<void>;
}

/**
 * What you own, and how you are wearing it.
 *
 * Getting a pack is not here — that is the marketplace, and buying something
 * and configuring it are different acts. This is the half you come back to:
 * the packs you have, and the pickers that put their pieces on.
 *
 * It sits apart from Settings › Profile, which is the account (address,
 * handle, password) rather than the face.
 */
export const UserSettingsDecorationsPage = ({
  user,
  refreshUser,
}: UserSettingsDecorationsPageProps) => {
  const { t } = useTranslation(["profiles", "common"]);
  const { data: library } = useMyDecorations();

  const [banner, setBanner] = useState(user.profile_decorations.banner ?? null);
  const [frame, setFrame] = useState(user.profile_decorations.frame ?? null);
  const [badges, setBadges] = useState<string[]>(user.profile_decorations.badges ?? []);

  // Giving a pack back takes its pieces off server-side, so the saved look can
  // change without this form touching it.
  useEffect(() => {
    setBanner(user.profile_decorations.banner ?? null);
    setFrame(user.profile_decorations.frame ?? null);
    setBadges(user.profile_decorations.badges ?? []);
  }, [user]);

  const save = useUpdateCurrentUser({
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

  const previewBanner = resolveDecoration(banner, "banner");

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{t("profiles:myPacks.title")}</CardTitle>
              <CardDescription>{t("profiles:myPacks.description")}</CardDescription>
            </div>
            <Button variant="outline" size="sm" asChild>
              <Link to="/marketplace">{t("profiles:myPacks.browse")}</Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <MyDecorationPacks />
        </CardContent>
      </Card>

      <Card className="overflow-hidden pt-0 shadow-sm">
        {/* The profile as it would look, above the controls that change it —
            the same arrangement the profile page itself has. */}
        <div
          className="h-24 w-full bg-center bg-cover bg-muted sm:h-32"
          style={previewBanner ? { backgroundImage: `url(${previewBanner.src})` } : undefined}
        />
        <CardContent className="space-y-6">
          <h2 className="sr-only">{t("profiles:look.title")}</h2>
          <div className="-mt-12 flex items-end gap-4">
            <ProfileAvatar
              user={user}
              decorations={{ banner, frame, badges }}
              className="size-20 rounded-full ring-4 ring-card"
            />
            <div className="min-w-0 flex-1 pb-1">
              <UserHandle user={user} className="font-semibold text-lg" />
            </div>
          </div>

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

          <Button
            disabled={!changed || save.isPending}
            onClick={() =>
              save.mutate({ profile_decorations: { banner, frame, badges } } as UserSelfUpdate)
            }
          >
            {save.isPending ? t("common:submitting") : t("profiles:look.save")}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
