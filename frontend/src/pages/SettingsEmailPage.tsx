import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import type { EmailSettings } from "@/types/api";

interface EmailPayload {
  host?: string | null;
  port?: number | null;
  secure: boolean;
  reject_unauthorized: boolean;
  username?: string | null;
  password?: string | null;
  from_address?: string | null;
  test_recipient?: string | null;
}

const DEFAULT_STATE = {
  host: "",
  port: "",
  secure: false,
  reject_unauthorized: true,
  username: "",
  from_address: "",
};

export const SettingsEmailPage = () => {
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === "admin";
  const [formState, setFormState] = useState(DEFAULT_STATE);
  const [password, setPassword] = useState("");
  const [testRecipient, setTestRecipient] = useState("");
  const emailQuery = useQuery<EmailSettings>({
    queryKey: ["settings", "email"],
    enabled: isPlatformAdmin,
    queryFn: async () => {
      const response = await apiClient.get<EmailSettings>("/settings/email");
      return response.data;
    },
  });

  useEffect(() => {
    if (emailQuery.data) {
      const data = emailQuery.data;
      setFormState({
        host: data.host ?? "",
        port: data.port ? String(data.port) : "",
        secure: data.secure,
        reject_unauthorized: data.reject_unauthorized,
        username: data.username ?? "",
        from_address: data.from_address ?? "",
      });
      setTestRecipient(data.test_recipient ?? "");
    }
  }, [emailQuery.data]);

  const updateMutation = useMutation({
    mutationFn: async (payload: EmailPayload) => {
      const response = await apiClient.put<EmailSettings>("/settings/email", payload);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success("Email settings saved");
      setPassword("");
      setTestRecipient(data.test_recipient ?? "");
      void emailQuery.refetch();
    },
    onError: () => toast.error("Unable to save email settings"),
  });

  const testMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post("/settings/email/test", {
        recipient: testRecipient || null,
      });
    },
    onSuccess: () => toast.success("Test email sent"),
    onError: () => toast.error("Unable to send test email"),
  });

  if (!isPlatformAdmin) {
    return (
      <p className="text-muted-foreground text-sm">
        Only platform admins can manage email settings.
      </p>
    );
  }

  if (emailQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading email settings…</p>;
  }

  if (emailQuery.isError || !emailQuery.data) {
    return <p className="text-destructive text-sm">Unable to load email settings.</p>;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload: EmailPayload = {
      host: formState.host || null,
      port: formState.port ? Number(formState.port) : null,
      secure: formState.secure,
      reject_unauthorized: formState.reject_unauthorized,
      username: formState.username || null,
      from_address: formState.from_address || null,
      test_recipient: testRecipient || null,
    };
    if (password) {
      payload.password = password;
    }
    updateMutation.mutate(payload);
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>SMTP email</CardTitle>
        <CardDescription>Configure the SMTP server used for transactional emails.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="smtp-host">Host</Label>
              <Input
                id="smtp-host"
                value={formState.host}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, host: event.target.value }))
                }
                placeholder="smtp.mailprovider.com"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="smtp-port">Port</Label>
              <Input
                id="smtp-port"
                type="number"
                min={1}
                max={65535}
                value={formState.port}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, port: event.target.value }))
                }
                placeholder="587"
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-center justify-between rounded-md border px-4 py-3">
              <div>
                <p className="font-medium">Secure (TLS) connection</p>
                <p className="text-muted-foreground text-sm">
                  Enable for port 465. Keep disabled for ports 587 or 25 (uses STARTTLS when
                  available).
                </p>
              </div>
              <Switch
                checked={formState.secure}
                onCheckedChange={(checked) =>
                  setFormState((prev) => ({ ...prev, secure: Boolean(checked) }))
                }
              />
            </div>
            <div className="flex items-center justify-between rounded-md border px-4 py-3">
              <div>
                <p className="font-medium">Reject unauthorized certificates</p>
                <p className="text-muted-foreground text-sm">
                  Disable only if you fully trust the mail server and understand the risk.
                </p>
              </div>
              <Switch
                checked={formState.reject_unauthorized}
                onCheckedChange={(checked) =>
                  setFormState((prev) => ({ ...prev, reject_unauthorized: Boolean(checked) }))
                }
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="smtp-username">Username</Label>
              <Input
                id="smtp-username"
                value={formState.username}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, username: event.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="smtp-password">Password</Label>
              <Input
                id="smtp-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={emailQuery.data.has_password ? "••••••••" : ""}
              />
              <p className="text-muted-foreground text-xs">
                Leave blank to keep the existing password.
              </p>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="smtp-from">From address</Label>
            <Input
              id="smtp-from"
              value={formState.from_address}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, from_address: event.target.value }))
              }
              placeholder={"Initiative <no-reply@example.com>"}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="smtp-test-recipient">Test email recipient</Label>
              <Input
                id="smtp-test-recipient"
                type="email"
                value={testRecipient}
                onChange={(event) => setTestRecipient(event.target.value)}
                placeholder="you@example.com"
              />
            </div>
            <div className="flex items-end">
              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => testMutation.mutate()}
                disabled={testMutation.isPending}
              >
                {testMutation.isPending ? "Sending…" : "Send test email"}
              </Button>
            </div>
          </div>
          <Button type="submit" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Saving…" : "Save email settings"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};
