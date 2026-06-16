import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

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
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { useInterfaceSettings, useUpdateInterfaceSettings } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { Capability, hasCapability } from "@/lib/permissions";

export const SettingsBrandingPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = hasCapability(user, Capability.configManage);
  const [lightColor, setLightColor] = useState("#2563eb");
  const [darkColor, setDarkColor] = useState("#60a5fa");

  const interfaceQuery = useInterfaceSettings({ enabled: isPlatformAdmin });

  const updateInterface = useUpdateInterfaceSettings({
    onSuccess: () => {
      toast.success(t("branding.interfaceSuccess"));
    },
  });

  useEffect(() => {
    if (interfaceQuery.data) {
      setLightColor(interfaceQuery.data.light_accent_color);
      setDarkColor(interfaceQuery.data.dark_accent_color);
    }
  }, [interfaceQuery.data]);

  const handleInterfaceSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateInterface.mutate({
      light_accent_color: lightColor,
      dark_accent_color: darkColor,
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
                <Label htmlFor="light-accent" className="font-medium text-sm">
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
                <Label htmlFor="dark-accent" className="font-medium text-sm">
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

      <Card>
        <CardHeader>
          <CardTitle>{t("branding.chesterPlayground.title")}</CardTitle>
          <CardDescription>{t("branding.chesterPlayground.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast(t("branding.chesterPlayground.default.message"))}
            >
              {t("branding.chesterPlayground.default.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.success(t("branding.chesterPlayground.success.message"))}
            >
              {t("branding.chesterPlayground.success.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.error(t("branding.chesterPlayground.error.message"))}
            >
              {t("branding.chesterPlayground.error.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.warning(t("branding.chesterPlayground.warning.message"))}
            >
              {t("branding.chesterPlayground.warning.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.info(t("branding.chesterPlayground.info.message"))}
            >
              {t("branding.chesterPlayground.info.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toast.loading(t("branding.chesterPlayground.loading.message"))}
            >
              {t("branding.chesterPlayground.loading.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                toast.success(t("branding.chesterPlayground.withDescription.message"), {
                  description: t("branding.chesterPlayground.withDescription.detail"),
                })
              }
            >
              {t("branding.chesterPlayground.withDescription.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                toast.info(t("branding.chesterPlayground.withAction.message"), {
                  action: {
                    label: t("branding.chesterPlayground.withAction.actionLabel"),
                    onClick: () =>
                      toast.success(t("branding.chesterPlayground.withAction.reverted")),
                  },
                })
              }
            >
              {t("branding.chesterPlayground.withAction.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast.warning(t("branding.chesterPlayground.sticky.message"), {
                  id: "chester-sticky",
                  duration: Infinity,
                });
              }}
            >
              {t("branding.chesterPlayground.sticky.label")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => toast.dismiss("chester-sticky")}>
              {t("branding.chesterPlayground.dismissSticky")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast.promise(new Promise((resolve) => setTimeout(() => resolve("done"), 2000)), {
                  loading: t("branding.chesterPlayground.promiseResolve.loading"),
                  success: t("branding.chesterPlayground.promiseResolve.success"),
                  error: t("branding.chesterPlayground.promiseReject.errorPrefix", {
                    message: "",
                  }),
                });
              }}
            >
              {t("branding.chesterPlayground.promiseResolve.label")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                toast
                  .promise(
                    new Promise((_, reject) => setTimeout(() => reject(new Error("boom")), 2000)),
                    {
                      loading: t("branding.chesterPlayground.promiseReject.loading"),
                      success: t("branding.chesterPlayground.promiseResolve.success"),
                      error: (err) =>
                        t("branding.chesterPlayground.promiseReject.errorPrefix", {
                          message: (err as Error).message,
                        }),
                    }
                  )
                  .catch(() => undefined);
              }}
            >
              {t("branding.chesterPlayground.promiseReject.label")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => toast.dismiss()}>
              {t("branding.chesterPlayground.dismissAll")}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
