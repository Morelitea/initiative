import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { ROLE_LABELS_QUERY_KEY, DEFAULT_ROLE_LABELS, useRoleLabels } from "../hooks/useRoleLabels";
import type { RoleLabels } from "../types/api";

const ROLE_FIELDS: { key: keyof RoleLabels; label: string; helper: string }[] = [
  { key: "admin", label: "Admin label", helper: "Shown anywhere the admin role appears." },
  {
    key: "project_manager",
    label: "Project manager label",
    helper: "Used for the project_manager role (e.g. “Team lead”).",
  },
  { key: "member", label: "Member label", helper: "Displayed for standard project members." },
];

export const SettingsRolesPage = () => {
  const roleLabelsQuery = useRoleLabels();
  const queryClient = useQueryClient();
  const [formState, setFormState] = useState<RoleLabels>(DEFAULT_ROLE_LABELS);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (roleLabelsQuery.data) {
      setFormState(roleLabelsQuery.data);
    }
  }, [roleLabelsQuery.data]);

  const updateLabels = useMutation({
    mutationFn: async (payload: RoleLabels) => {
      const response = await apiClient.put<RoleLabels>("/settings/roles", payload);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.setQueryData(ROLE_LABELS_QUERY_KEY, data);
      setMessage("Role labels updated");
    },
  });

  const handleChange = (role: keyof RoleLabels, value: string) => {
    setFormState((prev) => ({ ...prev, [role]: value }));
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    updateLabels.mutate(formState);
  };

  if (roleLabelsQuery.isLoading && !roleLabelsQuery.data) {
    return <p className="text-sm text-muted-foreground">Loading role labels…</p>;
  }

  if (roleLabelsQuery.isError) {
    return <p className="text-sm text-destructive">Unable to load role labels.</p>;
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>Role labels</CardTitle>
        <CardDescription>
          Customize how each project role is described throughout the workspace.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          {ROLE_FIELDS.map((field) => (
            <div key={field.key} className="space-y-2">
              <Label htmlFor={`role-label-${field.key}`}>{field.label}</Label>
              <Input
                id={`role-label-${field.key}`}
                value={formState[field.key]}
                onChange={(event) => handleChange(field.key, event.target.value)}
                maxLength={64}
                required
              />
              <p className="text-xs text-muted-foreground">{field.helper}</p>
            </div>
          ))}
          <div className="flex flex-col gap-2">
            <Button type="submit" disabled={updateLabels.isPending}>
              {updateLabels.isPending ? "Saving…" : "Save role labels"}
            </Button>
            {message ? <p className="text-sm text-primary">{message}</p> : null}
            {updateLabels.isError ? (
              <p className="text-sm text-destructive">Unable to update role labels.</p>
            ) : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
};
