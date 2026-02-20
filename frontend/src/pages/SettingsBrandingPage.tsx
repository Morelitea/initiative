import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { updateInterfaceSettingsApiV1SettingsInterfacePut } from "@/api/generated/settings/settings";
import { invalidateInterfaceSettings } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DEFAULT_ROLE_LABELS, useRoleLabels, useUpdateRoleLabels } from "@/hooks/useRoleLabels";
import { useAuth } from "@/hooks/useAuth";
import { useInterfaceSettings } from "@/hooks/useSettings";
import type { RoleLabelsResponse } from "@/api/generated/initiativeAPI.schemas";

interface InterfaceSettings {
  light_accent_color: string;
  dark_accent_color: string;
}

const ROLE_FIELDS: { key: keyof RoleLabelsResponse; labelKey: string; helperKey: string }[] = [
  { key: "admin", labelKey: "branding.adminLabel", helperKey: "branding.adminHelper" },
  {
    key: "project_manager",
    labelKey: "branding.projectManagerLabel",
    helperKey: "branding.projectManagerHelper",
  },
  { key: "member", labelKey: "branding.memberLabel", helperKey: "branding.memberHelper" },
];

export const SettingsBrandingPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === "admin";
  const [lightColor, setLightColor] = useState("#2563eb");
  const [darkColor, setDarkColor] = useState("#60a5fa");
  const [roleFormState, setRoleFormState] = useState<RoleLabelsResponse>(DEFAULT_ROLE_LABELS);
  const [roleMessage, setRoleMessage] = useState<string | null>(null);

  const interfaceQuery = useInterfaceSettings({ enabled: isPlatformAdmin });

  const updateInterface = useMutation({
    mutationFn: async (payload: InterfaceSettings) => {
      return updateInterfaceSettingsApiV1SettingsInterfacePut(
        payload as Parameters<typeof updateInterfaceSettingsApiV1SettingsInterfacePut>[0]
      ) as unknown as Promise<InterfaceSettings>;
    },
    onSuccess: () => {
      toast.success(t("branding.interfaceSuccess"));
      void invalidateInterfaceSettings();
    },
  });

  const roleLabelsQuery = useRoleLabels();

  const updateRoleLabels = useUpdateRoleLabels();

  useEffect(() => {
    if (interfaceQuery.data) {
      setLightColor(interfaceQuery.data.light_accent_color);
      setDarkColor(interfaceQuery.data.dark_accent_color);
    }
  }, [interfaceQuery.data]);

  useEffect(() => {
    if (roleLabelsQuery.data) {
      setRoleFormState(roleLabelsQuery.data);
    }
  }, [roleLabelsQuery.data]);

  const handleInterfaceSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateInterface.mutate({
      light_accent_color: lightColor,
      dark_accent_color: darkColor,
    });
  };

  const handleRoleChange = (role: keyof RoleLabelsResponse, value: string) => {
    setRoleFormState((prev) => ({ ...prev, [role]: value }));
  };

  const handleRoleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRoleMessage(null);
    updateRoleLabels.mutate(roleFormState, {
      onSuccess: () => setRoleMessage(t("branding.rolesSuccess")),
    });
  };

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("branding.adminOnly")}</p>;
  }

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("branding.colorsTitle")}</CardTitle>
          <CardDescription>{t("branding.colorsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {interfaceQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("branding.loadingInterface")}</p>
          ) : interfaceQuery.isError ? (
            <p className="text-destructive text-sm">{t("branding.interfaceError")}</p>
          ) : (
            <form className="grid gap-6 md:grid-cols-2" onSubmit={handleInterfaceSubmit}>
              <div className="space-y-3 rounded-lg border p-4">
                <Label htmlFor="light-accent" className="text-sm font-medium">
                  {t("branding.lightModeLabel")}
                </Label>
                <ColorPickerPopover
                  id="light-accent"
                  value={lightColor}
                  onChange={setLightColor}
                  triggerLabel={t("branding.adjust")}
                />
                <p className="text-muted-foreground text-xs">{t("branding.lightModeHelp")}</p>
              </div>

              <div className="space-y-3 rounded-lg border p-4">
                <Label htmlFor="dark-accent" className="text-sm font-medium">
                  {t("branding.darkModeLabel")}
                </Label>
                <ColorPickerPopover
                  id="dark-accent"
                  value={darkColor}
                  onChange={setDarkColor}
                  triggerLabel={t("branding.adjust")}
                />
                <p className="text-muted-foreground text-xs">{t("branding.darkModeHelp")}</p>
              </div>

              <CardFooter className="col-span-full flex flex-wrap gap-3 p-0 pt-2">
                <Button type="submit" disabled={updateInterface.isPending}>
                  {updateInterface.isPending
                    ? t("branding.savingInterface")
                    : t("branding.saveInterface")}
                </Button>
              </CardFooter>
            </form>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("branding.rolesTitle")}</CardTitle>
          <CardDescription>{t("branding.rolesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {roleLabelsQuery.isLoading && !roleLabelsQuery.data ? (
            <p className="text-muted-foreground text-sm">{t("branding.loadingRoles")}</p>
          ) : roleLabelsQuery.isError ? (
            <p className="text-destructive text-sm">{t("branding.rolesError")}</p>
          ) : (
            <form className="space-y-6" onSubmit={handleRoleSubmit}>
              {ROLE_FIELDS.map((field) => (
                <div key={field.key} className="space-y-2">
                  <Label htmlFor={`role-label-${field.key}`}>{t(field.labelKey as never)}</Label>
                  <Input
                    id={`role-label-${field.key}`}
                    value={roleFormState[field.key]}
                    onChange={(event) => handleRoleChange(field.key, event.target.value)}
                    maxLength={64}
                    required
                  />
                  <p className="text-muted-foreground text-xs">{t(field.helperKey as never)}</p>
                </div>
              ))}
              <div className="flex flex-col gap-2">
                <Button type="submit" disabled={updateRoleLabels.isPending}>
                  {updateRoleLabels.isPending ? t("branding.savingRoles") : t("branding.saveRoles")}
                </Button>
                {roleMessage ? <p className="text-primary text-sm">{roleMessage}</p> : null}
                {updateRoleLabels.isError ? (
                  <p className="text-destructive text-sm">{t("branding.rolesUpdateError")}</p>
                ) : null}
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
