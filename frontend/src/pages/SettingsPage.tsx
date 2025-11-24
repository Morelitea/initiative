import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { RegistrationSettings } from "../types/api";

const REGISTRATION_SETTINGS_QUERY_KEY = ["registration-settings"];

export const SettingsPage = () => {
  const { user } = useAuth();
  const [domainsInput, setDomainsInput] = useState("");

  const isAdmin = user?.role === "admin";

  const settingsQuery = useQuery<RegistrationSettings>({
    queryKey: REGISTRATION_SETTINGS_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<RegistrationSettings>("/settings/registration");
      return response.data;
    },
  });

  useEffect(() => {
    if (settingsQuery.data) {
      setDomainsInput(settingsQuery.data.auto_approved_domains.join(", "));
    }
  }, [settingsQuery.data]);

  const updateAllowList = useMutation({
    mutationFn: async (domains: string[]) => {
      const response = await apiClient.put<RegistrationSettings>("/settings/registration", {
        auto_approved_domains: domains,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDomainsInput(data.auto_approved_domains.join(", "));
      queryClient.setQueryData(REGISTRATION_SETTINGS_QUERY_KEY, data);
    },
  });

  const approveUser = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.post(`/users/${userId}/approve`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: REGISTRATION_SETTINGS_QUERY_KEY });
    },
  });

  if (!isAdmin) {
    return (
      <p className="text-sm text-muted-foreground">You need admin permissions to view this page.</p>
    );
  }

  if (settingsQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading settings…</p>;
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return <p className="text-sm text-destructive">Unable to load settings.</p>;
  }

  const handleDomainsSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const domains = domainsInput
      .split(",")
      .map((domain) => domain.trim().toLowerCase())
      .filter(Boolean);
    updateAllowList.mutate(domains);
  };

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Auto-approved email domains</CardTitle>
          <CardDescription>
            Enter a comma-separated list of domains that should be auto-approved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleDomainsSubmit}>
            <Input
              type="text"
              value={domainsInput}
              onChange={(event) => setDomainsInput(event.target.value)}
              placeholder="example.com, company.org"
            />
            <Button type="submit" disabled={updateAllowList.isPending}>
              {updateAllowList.isPending ? "Saving…" : "Save allow list"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Pending users</CardTitle>
          <CardDescription>
            Approve people who registered with non-allow-listed emails.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {settingsQuery.data.pending_users.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending accounts.</p>
          ) : (
            <div className="space-y-3">
              {settingsQuery.data.pending_users.map((pendingUser) => (
                <div
                  key={pendingUser.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-3"
                >
                  <div>
                    <p className="font-medium">{pendingUser.full_name ?? pendingUser.email}</p>
                    <p className="text-sm text-muted-foreground">{pendingUser.email}</p>
                  </div>
                  <Button
                    type="button"
                    onClick={() => approveUser.mutate(pendingUser.id)}
                    disabled={approveUser.isPending}
                  >
                    Approve
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
