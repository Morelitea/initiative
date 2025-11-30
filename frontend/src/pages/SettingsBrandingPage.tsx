import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
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
import { DEFAULT_ROLE_LABELS, ROLE_LABELS_QUERY_KEY, useRoleLabels } from "@/hooks/useRoleLabels";
import { useAuth } from "@/hooks/useAuth";
import type { RoleLabels } from "@/types/api";

interface InterfaceSettings {
  light_accent_color: string;
  dark_accent_color: string;
}

const ROLE_FIELDS: { key: keyof RoleLabels; label: string; helper: string }[] = [
  { key: "admin", label: "Admin label", helper: "Shown anywhere the admin role appears." },
  {
    key: "project_manager",
    label: "Project manager label",
    helper: "Used for the project_manager role (e.g. “Team lead”).",
  },
  { key: "member", label: "Member label", helper: "Displayed for standard project members." },
];

const INTERFACE_SETTINGS_QUERY_KEY = ["interface-settings"];

export const SettingsBrandingPage = () => {
  const { user } = useAuth();
  const isSuperUser = user?.id === 1;
  const queryClient = useQueryClient();

  const [lightColor, setLightColor] = useState("#2563eb");
  const [darkColor, setDarkColor] = useState("#60a5fa");
  const [roleFormState, setRoleFormState] = useState<RoleLabels>(DEFAULT_ROLE_LABELS);
  const [roleMessage, setRoleMessage] = useState<string | null>(null);

  const interfaceQuery = useQuery<InterfaceSettings>({
    queryKey: INTERFACE_SETTINGS_QUERY_KEY,
    enabled: isSuperUser,
    queryFn: async () => {
      const response = await apiClient.get<InterfaceSettings>("/settings/interface");
      return response.data;
    },
  });

  const updateInterface = useMutation({
    mutationFn: async (payload: InterfaceSettings) => {
      const response = await apiClient.put<InterfaceSettings>("/settings/interface", payload);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Interface settings updated");
      void queryClient.invalidateQueries({ queryKey: INTERFACE_SETTINGS_QUERY_KEY });
    },
  });

  const roleLabelsQuery = useRoleLabels();

  const updateRoleLabels = useMutation({
    mutationFn: async (payload: RoleLabels) => {
      const response = await apiClient.put<RoleLabels>("/settings/roles", payload);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(ROLE_LABELS_QUERY_KEY, data);
      setRoleMessage("Role labels updated");
    },
  });

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

  const handleRoleChange = (role: keyof RoleLabels, value: string) => {
    setRoleFormState((prev) => ({ ...prev, [role]: value }));
  };

  const handleRoleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRoleMessage(null);
    updateRoleLabels.mutate(roleFormState);
  };

  if (!isSuperUser) {
    return (
      <p className="text-muted-foreground text-sm">
        Only the initial super user can manage branding settings.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Brand colors</CardTitle>
          <CardDescription>Customize the accent colors for light and dark mode.</CardDescription>
        </CardHeader>
        <CardContent>
          {interfaceQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading interface settings…</p>
          ) : interfaceQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load interface settings.</p>
          ) : (
            <form className="grid gap-6 md:grid-cols-2" onSubmit={handleInterfaceSubmit}>
              <div className="space-y-3 rounded-lg border p-4">
                <Label htmlFor="light-accent" className="text-sm font-medium">
                  Light mode accent
                </Label>
                <ColorPickerPopover
                  id="light-accent"
                  value={lightColor}
                  onChange={setLightColor}
                  triggerLabel="Adjust"
                />
                <p className="text-muted-foreground text-xs">
                  Buttons, highlights, and focus states use this color while the app is in light
                  mode.
                </p>
              </div>

              <div className="space-y-3 rounded-lg border p-4">
                <Label htmlFor="dark-accent" className="text-sm font-medium">
                  Dark mode accent
                </Label>
                <ColorPickerPopover
                  id="dark-accent"
                  value={darkColor}
                  onChange={setDarkColor}
                  triggerLabel="Adjust"
                />
                <p className="text-muted-foreground text-xs">
                  Accent and primary elements use this color while dark mode is active.
                </p>
              </div>

              <CardFooter className="col-span-full flex flex-wrap gap-3 p-0 pt-2">
                <Button type="submit" disabled={updateInterface.isPending}>
                  {updateInterface.isPending ? "Saving…" : "Save interface settings"}
                </Button>
              </CardFooter>
            </form>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Role labels</CardTitle>
          <CardDescription>
            Customize how each project role is described throughout the workspace.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {roleLabelsQuery.isLoading && !roleLabelsQuery.data ? (
            <p className="text-muted-foreground text-sm">Loading role labels…</p>
          ) : roleLabelsQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load role labels.</p>
          ) : (
            <form className="space-y-6" onSubmit={handleRoleSubmit}>
              {ROLE_FIELDS.map((field) => (
                <div key={field.key} className="space-y-2">
                  <Label htmlFor={`role-label-${field.key}`}>{field.label}</Label>
                  <Input
                    id={`role-label-${field.key}`}
                    value={roleFormState[field.key]}
                    onChange={(event) => handleRoleChange(field.key, event.target.value)}
                    maxLength={64}
                    required
                  />
                  <p className="text-muted-foreground text-xs">{field.helper}</p>
                </div>
              ))}
              <div className="flex flex-col gap-2">
                <Button type="submit" disabled={updateRoleLabels.isPending}>
                  {updateRoleLabels.isPending ? "Saving…" : "Save role labels"}
                </Button>
                {roleMessage ? <p className="text-primary text-sm">{roleMessage}</p> : null}
                {updateRoleLabels.isError ? (
                  <p className="text-destructive text-sm">Unable to update role labels.</p>
                ) : null}
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
