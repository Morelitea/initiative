import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
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
  { label: "Sunday", value: 0 },
  { label: "Monday", value: 1 },
  { label: "Tuesday", value: 2 },
  { label: "Wednesday", value: 3 },
  { label: "Thursday", value: 4 },
  { label: "Friday", value: 5 },
  { label: "Saturday", value: 6 },
];

interface UserSettingsInterfacePageProps {
  user: User;
  refreshUser: () => Promise<void>;
}

export const UserSettingsInterfacePage = ({
  user,
  refreshUser,
}: UserSettingsInterfacePageProps) => {
  const [weekStartsOn, setWeekStartsOn] = useState(user.week_starts_on ?? 0);
  const [colorTheme, setColorTheme] = useState(user.color_theme ?? "kobold");

  useEffect(() => {
    setWeekStartsOn(user.week_starts_on ?? 0);
    setColorTheme(user.color_theme ?? "kobold");
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
      await refreshUser();
      toast.success("Interface preferences updated");
    },
    onError: () => {
      toast.error("Unable to update interface preferences");
      setWeekStartsOn(user.week_starts_on ?? 0);
      setColorTheme(user.color_theme ?? "kobold");
    },
  });

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Interface settings</CardTitle>
        <CardDescription>Customize your interface preferences.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">Color theme</p>
            <p className="text-muted-foreground text-sm">
              Choose a color theme for the application.
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
            <p className="font-medium">Week starts on</p>
            <p className="text-muted-foreground text-sm">
              Choose which day to show first on calendars and date pickers.
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
                {WEEK_START_OPTIONS.find((option) => option.value === weekStartsOn)?.label ??
                  "Sunday"}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {WEEK_START_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={String(option.value)}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
};
