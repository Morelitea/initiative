import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { UserRead, UserSelfUpdate } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { BadgePicker, SlotPicker } from "@/components/user/DecorationPicker";
import { DecorationStore } from "@/components/user/DecorationStore";
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
 * Where a profile gets its look: the store on top, what you own underneath.
 *
 * The two are one page because they are one task — you take a pack in order to
 * put it on, and the preview at the top is the thing both halves are aiming at.
 * It sits apart from Settings › Profile, which is the account (address, handle,
 * password) rather than the face.
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
          <CardTitle>{t("profiles:store.title")}</CardTitle>
          <CardDescription>{t("profiles:store.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <DecorationStore user={user} />
        </CardContent>
      </Card>

      <Card className="overflow-hidden pt-0 shadow-sm">
        {/* The profile as it would look, above the controls that change it —
            the same arrangement the page itself has. */}
        <div
          className="h-24 w-full bg-muted bg-center bg-cover sm:h-32"
          style={previewBanner ? { backgroundImage: `url(${previewBanner.src})` } : undefined}
        />
        <CardContent className="space-y-6">
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
