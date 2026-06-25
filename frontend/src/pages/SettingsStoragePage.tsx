import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { StorageSettingsUpdate } from "@/api/generated/initiativeAPI.schemas";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import {
  useStartStorageBackfill,
  useStorageBackfillStatus,
  useStorageSettings,
  useTestStorageConnection,
  useUpdateStorageSettings,
} from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { Capability, hasCapability } from "@/lib/permissions";

type Backend = "local" | "s3";

const DEFAULT_STATE = {
  backend: "local" as Backend,
  s3_bucket: "",
  s3_region: "us-east-1",
  s3_endpoint_url: "",
  s3_access_key_id: "",
  s3_use_path_style: false,
  s3_kms_key_id: "",
  s3_local_fallback: false,
};

export const SettingsStoragePage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = hasCapability(user, Capability.configManage);
  const [formState, setFormState] = useState(DEFAULT_STATE);
  const [secret, setSecret] = useState("");

  const storageQuery = useStorageSettings({ enabled: isPlatformAdmin });
  const hasSecret = storageQuery.data?.has_secret_access_key ?? false;

  const backfillStatus = useStorageBackfillStatus({
    enabled: isPlatformAdmin,
    // Poll while a run is in flight; idle otherwise.
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
  });
  const isBackfilling = backfillStatus.data?.status === "running";

  useEffect(() => {
    if (storageQuery.data) {
      const data = storageQuery.data;
      setFormState({
        backend: data.backend === "s3" ? "s3" : "local",
        s3_bucket: data.s3_bucket ?? "",
        s3_region: data.s3_region ?? "us-east-1",
        s3_endpoint_url: data.s3_endpoint_url ?? "",
        s3_access_key_id: data.s3_access_key_id ?? "",
        s3_use_path_style: data.s3_use_path_style,
        s3_kms_key_id: data.s3_kms_key_id ?? "",
        s3_local_fallback: data.s3_local_fallback,
      });
    }
  }, [storageQuery.data]);

  const buildPayload = (): StorageSettingsUpdate => {
    const payload: StorageSettingsUpdate = {
      backend: formState.backend,
      s3_bucket: formState.s3_bucket || null,
      s3_region: formState.s3_region || "us-east-1",
      s3_endpoint_url: formState.s3_endpoint_url || null,
      s3_access_key_id: formState.s3_access_key_id || null,
      s3_use_path_style: formState.s3_use_path_style,
      s3_kms_key_id: formState.s3_kms_key_id || null,
      s3_local_fallback: formState.s3_local_fallback,
    };
    // Only send the secret when the admin typed one, so an empty field keeps the
    // stored key (the backend treats "field absent" as "unchanged").
    if (secret) {
      payload.s3_secret_access_key = secret;
    }
    return payload;
  };

  const updateMutation = useUpdateStorageSettings({
    onSuccess: () => {
      toast.success(t("storage.saveSuccess"));
      setSecret("");
    },
    onError: () => toast.error(t("storage.saveError")),
  });

  const testMutation = useTestStorageConnection({
    onSuccess: (result) => {
      if (result.success) {
        toast.success(result.message || t("storage.testSuccess"));
      } else {
        toast.error(result.message || t("storage.testError"));
      }
    },
    onError: () => toast.error(t("storage.testError")),
  });

  const backfillMutation = useStartStorageBackfill({
    onSuccess: () => {
      toast.success(t("storage.backfillStarted"));
      void backfillStatus.refetch();
    },
    onError: () => toast.error(t("storage.backfillError")),
  });

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("storage.adminOnly")}</p>;
  }

  if (storageQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("storage.loading")}</p>;
  }

  if (storageQuery.isError || !storageQuery.data) {
    return <p className="text-destructive text-sm">{t("storage.loadError")}</p>;
  }

  const isS3 = formState.backend === "s3";

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateMutation.mutate(buildPayload());
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("storage.title")}</CardTitle>
        <CardDescription>{t("storage.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="storage-backend">{t("storage.backendLabel")}</Label>
            <Select
              value={formState.backend}
              onValueChange={(value) => {
                // Guard against a stray empty value (Radix can emit one during
                // mount in jsdom); only accept the two real backends.
                if (value === "local" || value === "s3") {
                  setFormState((prev) => ({ ...prev, backend: value }));
                }
              }}
            >
              <SelectTrigger id="storage-backend" className="w-full md:w-72">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="local">{t("storage.backendLocal")}</SelectItem>
                <SelectItem value="s3">{t("storage.backendS3")}</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("storage.backendHelp")}</p>
          </div>

          {isS3 && (
            <>
              <Alert>
                <AlertTitle>{t("storage.cutoverTitle")}</AlertTitle>
                <AlertDescription>{t("storage.cutoverHelp")}</AlertDescription>
              </Alert>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="s3-bucket">{t("storage.bucketLabel")}</Label>
                  <Input
                    id="s3-bucket"
                    value={formState.s3_bucket}
                    onChange={(event) =>
                      setFormState((prev) => ({ ...prev, s3_bucket: event.target.value }))
                    }
                    placeholder={t("storage.bucketPlaceholder")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="s3-region">{t("storage.regionLabel")}</Label>
                  <Input
                    id="s3-region"
                    value={formState.s3_region}
                    onChange={(event) =>
                      setFormState((prev) => ({ ...prev, s3_region: event.target.value }))
                    }
                    placeholder="us-east-1"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="s3-endpoint">{t("storage.endpointLabel")}</Label>
                <Input
                  id="s3-endpoint"
                  value={formState.s3_endpoint_url}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, s3_endpoint_url: event.target.value }))
                  }
                  placeholder={t("storage.endpointPlaceholder")}
                />
                <p className="text-muted-foreground text-xs">{t("storage.endpointHelp")}</p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="s3-access-key">{t("storage.accessKeyLabel")}</Label>
                  <Input
                    id="s3-access-key"
                    value={formState.s3_access_key_id}
                    onChange={(event) =>
                      setFormState((prev) => ({ ...prev, s3_access_key_id: event.target.value }))
                    }
                    placeholder={t("storage.accessKeyPlaceholder")}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="s3-secret-key">{t("storage.secretKeyLabel")}</Label>
                  <Input
                    id="s3-secret-key"
                    type="password"
                    value={secret}
                    onChange={(event) => setSecret(event.target.value)}
                    placeholder={hasSecret ? t("storage.secretKeySet") : ""}
                  />
                  <p className="text-muted-foreground text-xs">{t("storage.secretKeyHelp")}</p>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="s3-kms">{t("storage.kmsLabel")}</Label>
                <Input
                  id="s3-kms"
                  value={formState.s3_kms_key_id}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, s3_kms_key_id: event.target.value }))
                  }
                  placeholder={t("storage.kmsPlaceholder")}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="flex items-center justify-between rounded-md border px-4 py-3">
                  <div>
                    <p className="font-medium">{t("storage.pathStyleLabel")}</p>
                    <p className="text-muted-foreground text-sm">{t("storage.pathStyleHelp")}</p>
                  </div>
                  <Switch
                    checked={formState.s3_use_path_style}
                    onCheckedChange={(checked) =>
                      setFormState((prev) => ({ ...prev, s3_use_path_style: Boolean(checked) }))
                    }
                  />
                </div>
                <div className="flex items-center justify-between rounded-md border px-4 py-3">
                  <div>
                    <p className="font-medium">{t("storage.localFallbackLabel")}</p>
                    <p className="text-muted-foreground text-sm">
                      {t("storage.localFallbackHelp")}
                    </p>
                  </div>
                  <Switch
                    checked={formState.s3_local_fallback}
                    onCheckedChange={(checked) =>
                      setFormState((prev) => ({ ...prev, s3_local_fallback: Boolean(checked) }))
                    }
                  />
                </div>
              </div>
            </>
          )}

          <div className="flex flex-wrap gap-3">
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? t("storage.saving") : t("storage.save")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => testMutation.mutate(buildPayload())}
              disabled={testMutation.isPending || !isS3}
            >
              {testMutation.isPending ? t("storage.testing") : t("storage.testConnection")}
            </Button>
          </div>
        </form>

        <div className="mt-8 space-y-3 border-t pt-6">
          <div>
            <h3 className="font-medium">{t("storage.backfillTitle")}</h3>
            <p className="text-muted-foreground text-sm">{t("storage.backfillHelp")}</p>
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => backfillMutation.mutate()}
            disabled={backfillMutation.isPending || isBackfilling}
          >
            {isBackfilling ? t("storage.backfillRunning") : t("storage.startBackfill")}
          </Button>
          {backfillStatus.data && backfillStatus.data.status !== "idle" && (
            <div className="rounded-md border px-4 py-3 text-sm">
              <p className="font-medium">
                {t(`storage.backfillStatus.${backfillStatus.data.status}`)}
              </p>
              <p className="text-muted-foreground">
                {t("storage.backfillCounts", {
                  copied: backfillStatus.data.copied,
                  skipped: backfillStatus.data.skipped,
                  failed: backfillStatus.data.failed,
                })}
              </p>
              {backfillStatus.data.error && (
                <p className="text-destructive">{backfillStatus.data.error}</p>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
};
