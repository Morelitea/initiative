import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  const [showSidebar, setShowSidebar] = useState(user.show_project_sidebar ?? true);
  const [showTabs, setShowTabs] = useState(user.show_project_tabs ?? false);
  const [weekStartsOn, setWeekStartsOn] = useState(user.week_starts_on ?? 0);

  useEffect(() => {
    setShowSidebar(user.show_project_sidebar ?? true);
    setShowTabs(user.show_project_tabs ?? false);
    setWeekStartsOn(user.week_starts_on ?? 0);
  }, [user]);

  const updateInterfacePrefs = useMutation({
    mutationFn: async (payload: Record<string, boolean | number>) => {
      await apiClient.patch<User>("/users/me", payload);
    },
    onSuccess: async (_, variables) => {
      if (variables.show_project_sidebar !== undefined) {
        setShowSidebar(Boolean(variables.show_project_sidebar));
      }
      if (variables.show_project_tabs !== undefined) {
        setShowTabs(Boolean(variables.show_project_tabs));
      }
      if (variables.week_starts_on !== undefined) {
        setWeekStartsOn(Number(variables.week_starts_on));
      }
      await refreshUser();
      toast.success("Interface preferences updated");
    },
    onError: () => {
      toast.error("Unable to update interface preferences");
      setShowSidebar(user.show_project_sidebar ?? true);
      setShowTabs(user.show_project_tabs ?? false);
      setWeekStartsOn(user.week_starts_on ?? 0);
    },
  });

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Interface settings</CardTitle>
        <CardDescription>Choose how project shortcuts appear across the app.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium">Sidebar shortcuts</p>
            <p className="text-muted-foreground text-sm">
              Show favorite and recent projects in the left sidebar.
            </p>
          </div>
          <Switch
            checked={showSidebar}
            onCheckedChange={(checked) => {
              setShowSidebar(checked);
              updateInterfacePrefs.mutate({ show_project_sidebar: checked });
            }}
            disabled={updateInterfacePrefs.isPending}
          />
        </div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="font-medium">Project tabs</p>
            <p className="text-muted-foreground text-sm">
              Show recently opened projects as tabs below the header.
            </p>
          </div>
          <Switch
            checked={showTabs}
            onCheckedChange={(checked) => {
              setShowTabs(checked);
              updateInterfacePrefs.mutate({ show_project_tabs: checked });
            }}
            disabled={updateInterfacePrefs.isPending}
          />
        </div>
        <div className="flex flex-col gap-4 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
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
