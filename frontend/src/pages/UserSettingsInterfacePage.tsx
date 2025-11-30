import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import type { User } from "@/types/api";

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

  useEffect(() => {
    setShowSidebar(user.show_project_sidebar ?? true);
    setShowTabs(user.show_project_tabs ?? false);
  }, [user]);

  const updateInterfacePrefs = useMutation({
    mutationFn: async (payload: Record<string, boolean>) => {
      await apiClient.patch<User>("/users/me", payload);
    },
    onSuccess: async (_, variables) => {
      if (variables.show_project_sidebar !== undefined) {
        setShowSidebar(Boolean(variables.show_project_sidebar));
      }
      if (variables.show_project_tabs !== undefined) {
        setShowTabs(Boolean(variables.show_project_tabs));
      }
      await refreshUser();
      toast.success("Interface preferences updated");
    },
    onError: () => {
      toast.error("Unable to update interface preferences");
      setShowSidebar(user.show_project_sidebar ?? true);
      setShowTabs(user.show_project_tabs ?? false);
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
      </CardContent>
    </Card>
  );
};
