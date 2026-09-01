/**
 * `/settings/access` — who else can reach this tool entity.
 *
 * Write access to the entity is what the tab bar offers this section on, and
 * the section refuses it on its own too: the address is typeable, and sharing
 * is the last privilege gate in front of the entity's contents.
 */

import { useTranslation } from "react-i18next";

import { ShareControl } from "@/components/access/ShareControl";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { ToolSettingsPermissionRequired } from "@/components/tools/settings/ToolSettingsGuard";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "@/lib/chesterToast";

export const ToolSettingsAccessPage = () => {
  const { t } = useTranslation(["common", "access"]);
  const { entity, canManage, isOwner, setGrants } = useToolSettings();

  if (!canManage) {
    return <ToolSettingsPermissionRequired />;
  }

  const ownerId = entity.grants.find((grant) => grant.level === "owner")?.user_id ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("common:toolSettings.tabAccess")}</CardTitle>
        <CardDescription>{t("access:share.settingsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <ShareControl
          initiativeId={entity.initiative_id ?? 0}
          grants={entity.grants}
          ownerId={ownerId}
          onChange={(grants) =>
            setGrants.mutate(grants, {
              onSuccess: () => toast.success(t("common:toolSettings.permissionsUpdated")),
            })
          }
          disabled={!isOwner || setGrants.isPending}
        />
      </CardContent>
    </Card>
  );
};
