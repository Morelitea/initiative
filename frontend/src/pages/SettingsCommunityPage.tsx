/**
 * The community-directory switch (platform settings → Community).
 *
 * One decision, and it belongs to the platform owner rather than to any guild:
 * whether this deployment has a community directory at all. Guilds decide
 * whether to be *in* it from their own settings page; this decides whether it
 * exists for them to be in.
 *
 * The current value comes from the SPA's boot config rather than a settings
 * read, because it is the same value every other page reads to decide whether
 * to offer the directory — there is one source, not an owner's copy and
 * everyone else's.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useCommunitySettings, useUpdateCommunitySettings } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

export const SettingsCommunityPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = hasCapability(user, Capability.configManage);
  const { communityDirectoryEnabled, communityAgeGateEnabled, isLoading } = useAppConfig();
  const { data: community } = useCommunitySettings();
  // Turning the age gate off is an assertion about every account here, not a
  // preference, so it is confirmed. Turning it back on is not.
  const [confirmingAgeGateOff, setConfirmingAgeGateOff] = useState(false);

  const update = useUpdateCommunitySettings({
    onSuccess: (result) => {
      toast.success(
        result.community_directory_enabled
          ? t("community.enabledToast")
          : t("community.disabledToast")
      );
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:community.saveError"));
    },
  });

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("community.adminOnly")}</p>;
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("community.title")}</CardTitle>
        <CardDescription>{t("community.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-3">
          <Switch
            id="community-directory-enabled"
            checked={communityDirectoryEnabled}
            disabled={isLoading || update.isPending}
            onCheckedChange={(checked) =>
              update.mutate({ community_directory_enabled: Boolean(checked) })
            }
          />
          <Label htmlFor="community-directory-enabled">{t("community.toggleLabel")}</Label>
        </div>
        <p className="text-muted-foreground text-sm">{t("community.helpText")}</p>
        {/* Turning it back off is not a punishment for the guilds that opted
            in, and saying so up front stops it reading like one. */}
        <p className="text-muted-foreground text-xs">{t("community.reversibleNote")}</p>

        {/* The second switch. Shown regardless of the first, so an owner can
            settle it before opening the directory rather than discovering it
            once people are already arriving. */}
        <div className="space-y-4 border-t pt-4">
          <div className="flex items-center gap-3">
            <Switch
              id="community-age-gate-enabled"
              checked={communityAgeGateEnabled}
              disabled={isLoading || update.isPending}
              onCheckedChange={(checked) => {
                if (checked) {
                  update.mutate({
                    community_directory_enabled: communityDirectoryEnabled,
                    age_gate_enabled: true,
                  });
                  return;
                }
                setConfirmingAgeGateOff(true);
              }}
            />
            <Label htmlFor="community-age-gate-enabled">{t("community.ageGateLabel")}</Label>
          </div>
          <p className="text-muted-foreground text-sm">{t("community.ageGateHelpText")}</p>
        </div>

        {/* The third decision. Not a switch and not on the boot config: it is
            read once, when an account is made, so changing it moves nobody who
            is already here. */}
        <div className="space-y-2 border-t pt-4">
          <Label htmlFor="default-dm-policy">{t("community.defaultDmLabel")}</Label>
          <Select
            value={community?.default_dm_policy ?? "private"}
            disabled={isLoading || update.isPending || !community}
            onValueChange={(value) =>
              update.mutate({
                community_directory_enabled: communityDirectoryEnabled,
                default_dm_policy: value as DmPolicy,
              })
            }
          >
            <SelectTrigger id="default-dm-policy" className="max-w-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="private">{t("privacy.dm.private")}</SelectItem>
              <SelectItem value="community">{t("privacy.dm.community")}</SelectItem>
              <SelectItem value="public">{t("privacy.dm.public")}</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-sm">{t("community.defaultDmHelpText")}</p>
        </div>

        <ConfirmDialog
          open={confirmingAgeGateOff}
          onOpenChange={setConfirmingAgeGateOff}
          title={t("community.ageGateOffTitle")}
          description={t("community.ageGateOffBody")}
          confirmLabel={t("community.ageGateOffConfirm")}
          onConfirm={() =>
            update.mutate({
              community_directory_enabled: communityDirectoryEnabled,
              age_gate_enabled: false,
            })
          }
        />
      </CardContent>
    </Card>
  );
};
