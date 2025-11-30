import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { queryClient } from "@/lib/queryClient";
import type { ApiKeyCreateResponse, ApiKeyListResponse, ApiKeyMetadata } from "@/types/api";
import { Input } from "@/components/ui/input";
import { DateTimePicker } from "@/components/ui/date-time-picker";

const API_KEYS_QUERY_KEY = ["settings", "api-keys"] as const;

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return "—";
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));
  } catch {
    return value;
  }
};

const computeStatus = (key: ApiKeyMetadata) => {
  if (!key.is_active) {
    return { label: "Disabled", variant: "destructive" as const };
  }
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) {
    return { label: "Expired", variant: "secondary" as const };
  }
  return { label: "Active", variant: "default" as const };
};

export const SettingsApiKeysPage = () => {
  const [name, setName] = useState("");
  const [expiresAtInput, setExpiresAtInput] = useState("");
  const [generatedSecret, setGeneratedSecret] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const apiKeysQuery = useQuery<ApiKeyListResponse>({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<ApiKeyListResponse>("/settings/api-keys");
      return response.data;
    },
  });

  const createKey = useMutation({
    mutationFn: async (payload: { name: string; expires_at?: string | null }) => {
      const response = await apiClient.post<ApiKeyCreateResponse>("/settings/api-keys", payload);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success("API key created");
      setGeneratedSecret(data.secret);
      setName("");
      setExpiresAtInput("");
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
    },
    onError: () => {
      toast.error("Unable to create API key");
    },
  });

  const deleteKey = useMutation({
    mutationFn: async (apiKeyId: number) => {
      await apiClient.delete(`/settings/api-keys/${apiKeyId}`);
    },
    onMutate: (keyId: number) => {
      setDeleteTarget(keyId);
    },
    onSuccess: () => {
      toast.success("API key deleted");
      void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
    },
    onError: () => {
      toast.error("Unable to delete API key");
    },
    onSettled: () => {
      setDeleteTarget(null);
    },
  });

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error("Name is required");
      return;
    }
    const payload: { name: string; expires_at?: string | null } = { name: trimmedName };
    if (expiresAtInput) {
      const parsed = new Date(expiresAtInput);
      if (!Number.isNaN(parsed.getTime())) {
        payload.expires_at = parsed.toISOString();
      }
    }
    createKey.mutate(payload);
  };

  const apiKeys = useMemo(() => apiKeysQuery.data?.keys ?? [], [apiKeysQuery.data?.keys]);

  const copySecret = () => {
    if (!generatedSecret || !navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(generatedSecret).then(() => {
      toast.success("API key copied to clipboard");
    });
  };

  return (
    <div className="space-y-6">
      {generatedSecret ? (
        <Card className="border-primary/50 shadow-sm">
          <CardHeader>
            <CardTitle>New API key</CardTitle>
            <CardDescription>
              Copy this key now. You will not be able to view it again.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-start gap-4">
            <code className="bg-muted flex-1 rounded-md border px-3 py-2 font-mono text-sm break-all">
              {generatedSecret}
            </code>
            <Button type="button" variant="secondary" onClick={copySecret}>
              Copy
            </Button>
          </CardContent>
        </Card>
      ) : null}

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Generate an API key</CardTitle>
          <CardDescription>
            Create long-lived credentials for scripts or integrations.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleCreate}>
            <div className="space-y-2">
              <Label htmlFor="api-key-name">Key name</Label>
              <Input
                id="api-key-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="e.g. reporting-script"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="api-key-expiration">Expiration (optional)</Label>
              <DateTimePicker
                id="api-key-expiration"
                value={expiresAtInput}
                onChange={setExpiresAtInput}
                placeholder="Never expires"
              />
              <p className="text-muted-foreground text-xs">
                Leave blank for a key that never expires.
              </p>
            </div>
            <Button type="submit" disabled={createKey.isPending}>
              {createKey.isPending ? "Generating…" : "Generate API key"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Existing keys</CardTitle>
          <CardDescription>
            Only the last few characters are shown. Rotate keys regularly.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {apiKeysQuery.isLoading ? (
            <p className="text-muted-foreground text-sm">Loading API keys…</p>
          ) : apiKeysQuery.isError ? (
            <p className="text-destructive text-sm">Unable to load API keys.</p>
          ) : apiKeys.length === 0 ? (
            <p className="text-muted-foreground text-sm">No API keys yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted-foreground text-left">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Name</th>
                    <th className="py-2 pr-4 font-medium">Prefix</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 pr-4 font-medium">Last used</th>
                    <th className="py-2 pr-4 font-medium">Expires</th>
                    <th className="py-2 text-right font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map((key) => {
                    const status = computeStatus(key);
                    return (
                      <tr key={key.id} className="border-t">
                        <td className="py-3 pr-4">
                          <div className="font-medium">{key.name}</div>
                          <div className="text-muted-foreground text-xs">
                            {formatDateTime(key.created_at)}
                          </div>
                        </td>
                        <td className="py-3 pr-4 font-mono">{key.token_prefix}•••</td>
                        <td className="py-3 pr-4">
                          <Badge variant={status.variant}>{status.label}</Badge>
                        </td>
                        <td className="py-3 pr-4">
                          {key.last_used_at ? formatDateTime(key.last_used_at) : "Never"}
                        </td>
                        <td className="py-3 pr-4">{formatDateTime(key.expires_at)}</td>
                        <td className="py-3 text-right">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => deleteKey.mutate(key.id)}
                            disabled={deleteTarget === key.id && deleteKey.isPending}
                          >
                            {deleteTarget === key.id && deleteKey.isPending
                              ? "Removing…"
                              : "Delete"}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
