import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  updateEmailSettingsApiV1SettingsEmailPut,
  sendTestEmailApiV1SettingsEmailTestPost,
} from "@/api/generated/settings/settings";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useEmailSettings } from "@/hooks/useSettings";
import type { EmailSettingsResponse } from "@/api/generated/initiativeAPI.schemas";

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
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === "admin";
  const [formState, setFormState] = useState(DEFAULT_STATE);
  const [password, setPassword] = useState("");
  const [testRecipient, setTestRecipient] = useState("");
  const emailQuery = useEmailSettings({ enabled: isPlatformAdmin });

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
      return updateEmailSettingsApiV1SettingsEmailPut(
        payload as Parameters<typeof updateEmailSettingsApiV1SettingsEmailPut>[0]
      ) as unknown as Promise<EmailSettingsResponse>;
    },
    onSuccess: (data) => {
      toast.success(t("email.saveSuccess"));
      setPassword("");
      setTestRecipient(data.test_recipient ?? "");
      void emailQuery.refetch();
    },
    onError: () => toast.error(t("email.saveError")),
  });

  const testMutation = useMutation({
    mutationFn: async () => {
      await sendTestEmailApiV1SettingsEmailTestPost({
        recipient: testRecipient || null,
      } as Parameters<typeof sendTestEmailApiV1SettingsEmailTestPost>[0]);
    },
    onSuccess: () => toast.success(t("email.testSuccess")),
    onError: () => toast.error(t("email.testError")),
  });

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("email.adminOnly")}</p>;
  }

  if (emailQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("email.loading")}</p>;
  }

  if (emailQuery.isError || !emailQuery.data) {
    return <p className="text-destructive text-sm">{t("email.loadError")}</p>;
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
        <CardTitle>{t("email.title")}</CardTitle>
        <CardDescription>{t("email.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="smtp-host">{t("email.hostLabel")}</Label>
              <Input
                id="smtp-host"
                value={formState.host}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, host: event.target.value }))
                }
                placeholder={t("email.hostPlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="smtp-port">{t("email.portLabel")}</Label>
              <Input
                id="smtp-port"
                type="number"
                min={1}
                max={65535}
                value={formState.port}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, port: event.target.value }))
                }
                placeholder={t("email.portPlaceholder")}
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex items-center justify-between rounded-md border px-4 py-3">
              <div>
                <p className="font-medium">{t("email.secureLabel")}</p>
                <p className="text-muted-foreground text-sm">{t("email.secureHelp")}</p>
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
                <p className="font-medium">{t("email.rejectUnauthorizedLabel")}</p>
                <p className="text-muted-foreground text-sm">{t("email.rejectUnauthorizedHelp")}</p>
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
              <Label htmlFor="smtp-username">{t("email.usernameLabel")}</Label>
              <Input
                id="smtp-username"
                value={formState.username}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, username: event.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="smtp-password">{t("email.passwordLabel")}</Label>
              <Input
                id="smtp-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={emailQuery.data.has_password ? t("email.passwordPlaceholder") : ""}
              />
              <p className="text-muted-foreground text-xs">{t("email.passwordHelp")}</p>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="smtp-from">{t("email.fromAddressLabel")}</Label>
            <Input
              id="smtp-from"
              value={formState.from_address}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, from_address: event.target.value }))
              }
              placeholder={t("email.fromAddressPlaceholder")}
            />
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="smtp-test-recipient">{t("email.testRecipientLabel")}</Label>
              <Input
                id="smtp-test-recipient"
                type="email"
                value={testRecipient}
                onChange={(event) => setTestRecipient(event.target.value)}
                placeholder={t("email.testRecipientPlaceholder")}
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
                {testMutation.isPending ? t("email.sendingTest") : t("email.sendTest")}
              </Button>
            </div>
          </div>
          <Button type="submit" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? t("email.saving") : t("email.save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
};
