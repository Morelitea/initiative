import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getThemeList } from "@/lib/themes";
import type { User } from "@/types/api";

const WEEK_START_OPTIONS = [
  { labelKey: "dates:weekdays.sunday", value: 0 },
  { labelKey: "dates:weekdays.monday", value: 1 },
  { labelKey: "dates:weekdays.tuesday", value: 2 },
  { labelKey: "dates:weekdays.wednesday", value: 3 },
  { labelKey: "dates:weekdays.thursday", value: 4 },
  { labelKey: "dates:weekdays.friday", value: 5 },
  { labelKey: "dates:weekdays.saturday", value: 6 },
];

const LANGUAGE_OPTIONS = [
  { label: "English", value: "en" },
  { label: "Español", value: "es" },
  { label: "[Pseudo]", value: "pseudo" },
];

interface UserSettingsInterfacePageProps {
  user: User;
  refreshUser: () => Promise<void>;
}

export const UserSettingsInterfacePage = ({
  user,
  refreshUser,
}: UserSettingsInterfacePageProps) => {
  const { t, i18n } = useTranslation(["settings", "dates"]);
  const [weekStartsOn, setWeekStartsOn] = useState(user.week_starts_on ?? 0);
  const [colorTheme, setColorTheme] = useState(user.color_theme ?? "kobold");
  const [locale, setLocale] = useState(user.locale ?? "en");

  useEffect(() => {
    setWeekStartsOn(user.week_starts_on ?? 0);
    setColorTheme(user.color_theme ?? "kobold");
    setLocale(user.locale ?? "en");
  }, [user]);

  const updateInterfacePrefs = useMutation({
    mutationFn: async (payload: Record<string, boolean | number | string>) => {
      await apiClient.patch<User>("/users/me", payload);
    },
    onSuccess: async (_, variables) => {
      if (variables.week_starts_on !== undefined) {
        setWeekStartsOn(Number(variables.week_starts_on));
      }
      if (variables.color_theme !== undefined) {
        setColorTheme(String(variables.color_theme));
      }
      if (variables.locale !== undefined) {
        const newLocale = String(variables.locale);
        setLocale(newLocale);
        void i18n.changeLanguage(newLocale);
      }
      await refreshUser();
      toast.success(t("interface.updateSuccess"));
    },
    onError: () => {
      toast.error(t("interface.updateError"));
      setWeekStartsOn(user.week_starts_on ?? 0);
      setColorTheme(user.color_theme ?? "kobold");
      setLocale(user.locale ?? "en");
    },
  });

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("interface.title")}</CardTitle>
        <CardDescription>{t("interface.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">{t("interface.language")}</p>
            <p className="text-muted-foreground text-sm">{t("interface.languageDescription")}</p>
          </div>
          <Select
            value={locale}
            onValueChange={(next) => {
              setLocale(next);
              updateInterfacePrefs.mutate({ locale: next });
            }}
            disabled={updateInterfacePrefs.isPending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {LANGUAGE_OPTIONS.find((l) => l.value === locale)?.label ?? "English"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {LANGUAGE_OPTIONS.map((lang) => (
                <SelectItem key={lang.value} value={lang.value}>
                  {lang.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">{t("interface.colorTheme")}</p>
            <p className="text-muted-foreground text-sm">{t("interface.colorThemeDescription")}</p>
          </div>
          <Select
            value={colorTheme}
            onValueChange={(next) => {
              setColorTheme(next);
              updateInterfacePrefs.mutate({ color_theme: next });
            }}
            disabled={updateInterfacePrefs.isPending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {getThemeList().find((t) => t.id === colorTheme)?.name ?? "Kobold"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {getThemeList().map((theme) => (
                <SelectItem key={theme.id} value={theme.id}>
                  {theme.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">{t("interface.weekStartsOn")}</p>
            <p className="text-muted-foreground text-sm">
              {t("interface.weekStartsOnDescription")}
            </p>
          </div>
          <Select
            value={String(weekStartsOn)}
            onValueChange={(next) => {
              const value = Number(next);
              setWeekStartsOn(value);
              updateInterfacePrefs.mutate({ week_starts_on: value });
            }}
            disabled={updateInterfacePrefs.isPending}
          >
            <SelectTrigger className="sm:w-52">
              <SelectValue>
                {t(
                  WEEK_START_OPTIONS.find((option) => option.value === weekStartsOn)?.labelKey ??
                    "dates:weekdays.sunday"
                )}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {WEEK_START_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={String(option.value)}>
                  {t(option.labelKey)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
};
