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

import { useTranslation } from "react-i18next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useUpdateCommunitySettings } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

export const SettingsCommunityPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = hasCapability(user, Capability.configManage);
  const { communityDirectoryEnabled, isLoading } = useAppConfig();

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
      </CardContent>
    </Card>
  );
};
