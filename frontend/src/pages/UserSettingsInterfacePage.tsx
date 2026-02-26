import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useUpdateCurrentUser } from "@/hooks/useUsers";
import { getTheme, getThemeList } from "@/lib/themes";
import type { ThemeColors } from "@/lib/themes";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

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
];

function MiniMockup({ colors }: { colors: ThemeColors }) {
  const c = (value: string): string => `oklch(${value})`;

  return (
    <div
      className="flex overflow-hidden rounded-lg border"
      style={{
        height: 130,
        borderColor: c(colors.border),
        backgroundColor: c(colors.background),
      }}
    >
      {/* Sidebar strip */}
      <div
        className="flex flex-col gap-1.5 p-1.5"
        style={{ width: 28, backgroundColor: c(colors.sidebar) }}
      >
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.sidebarPrimary) }}
        />
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.muted) }}
        />
        <div
          className="rounded"
          style={{ height: 6, width: "100%", backgroundColor: c(colors.muted) }}
        />
      </div>

      {/* Main area */}
      <div className="flex flex-1 flex-col gap-2 p-2">
        {/* Mini card */}
        <div
          className="flex flex-col gap-1.5 rounded p-2"
          style={{ backgroundColor: c(colors.card) }}
        >
          <div
            className="rounded"
            style={{
              height: 6,
              width: "80%",
              backgroundColor: c(colors.foreground),
              opacity: 0.8,
            }}
          />
          <div
            className="rounded"
            style={{
              height: 4,
              width: "50%",
              backgroundColor: c(colors.mutedForeground),
              opacity: 0.6,
            }}
          />
          <div className="mt-1 flex gap-1">
            <div
              className="rounded"
              style={{ height: 8, width: 24, backgroundColor: c(colors.ring) }}
            />
            <div
              className="rounded"
              style={{ height: 8, width: 24, backgroundColor: c(colors.border) }}
            />
          </div>
        </div>

        {/* Chart color swatches */}
        <div className="flex gap-0.5">
          {[colors.chart1, colors.chart2, colors.chart3, colors.chart4, colors.chart5].map(
            (color, i) => (
              <div
                key={i}
                className="flex-1 rounded-sm"
                style={{ height: 6, backgroundColor: c(color) }}
              />
            )
          )}
        </div>
      </div>
    </div>
  );
}

function ThemeColorPreview({ themeId }: { themeId: string }) {
  const { t } = useTranslation("settings");
  const theme = getTheme(themeId);

  if (!theme) {
    return null;
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("interface.themePreview")}</CardTitle>
        <CardDescription>{theme.description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <p className="text-muted-foreground text-xs font-medium">{t("interface.lightMode")}</p>
            <MiniMockup colors={theme.light} />
          </div>
          <div className="space-y-1.5">
            <p className="text-muted-foreground text-xs font-medium">{t("interface.darkMode")}</p>
            <MiniMockup colors={theme.dark} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

interface UserSettingsInterfacePageProps {
  user: UserRead;
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

  const updateInterfacePrefs = useUpdateCurrentUser({
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
    <div className="space-y-4">
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
              <p className="text-muted-foreground text-sm">
                {t("interface.colorThemeDescription")}
              </p>
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
                    (WEEK_START_OPTIONS.find((option) => option.value === weekStartsOn)?.labelKey ??
                      "dates:weekdays.sunday") as never
                  )}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {WEEK_START_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={String(option.value)}>
                    {t(option.labelKey as never)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <ThemeColorPreview themeId={colorTheme} />
    </div>
  );
};
