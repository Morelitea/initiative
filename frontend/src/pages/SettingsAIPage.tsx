import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ModelCombobox } from "@/components/ui/model-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  usePlatformAISettings,
  useUpdatePlatformAISettings,
  useTestAIConnection,
  useFetchAIModels,
} from "@/hooks/useAISettings";
import { useAuth } from "@/hooks/useAuth";
import { getModelsForProvider, PROVIDER_CONFIGS } from "@/lib/ai-providers";
import type { AIProvider, PlatformAISettingsUpdate } from "@/api/generated/initiativeAPI.schemas";

interface FormState {
  enabled: boolean;
  provider: AIProvider | "";
  apiKey: string;
  baseUrl: string;
  model: string;
  allowGuildOverride: boolean;
  allowUserOverride: boolean;
}

const DEFAULT_STATE: FormState = {
  enabled: false,
  provider: "",
  apiKey: "",
  baseUrl: "",
  model: "",
  allowGuildOverride: true,
  allowUserOverride: true,
};

export const SettingsAIPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === "admin";
  const [formState, setFormState] = useState<FormState>(DEFAULT_STATE);
  const [hasExistingKey, setHasExistingKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  const settingsQuery = usePlatformAISettings({ enabled: isPlatformAdmin });

  useEffect(() => {
    if (settingsQuery.data) {
      const data = settingsQuery.data;
      setFormState({
        enabled: data.enabled,
        provider: data.provider ?? "",
        apiKey: "",
        baseUrl: data.base_url ?? "",
        model: data.model ?? "",
        allowGuildOverride: data.allow_guild_override,
        allowUserOverride: data.allow_user_override,
      });
      setHasExistingKey(data.has_api_key);
    }
  }, [settingsQuery.data]);

  const updateMutation = useUpdatePlatformAISettings({
    onSuccess: (data) => {
      toast.success(t("ai.saveSuccess"));
      setFormState((prev) => ({ ...prev, apiKey: "" }));
      setHasExistingKey(data.has_api_key);
    },
    onError: () => toast.error(t("ai.saveError")),
  });

  const testMutation = useTestAIConnection({
    onSuccess: (data) => {
      if (data.success) {
        toast.success(data.message);
        if (data.available_models) {
          setAvailableModels(data.available_models);
        }
      } else {
        toast.error(data.message);
      }
    },
    onError: () => toast.error(t("ai.testError")),
  });

  const fetchModelsMutation = useFetchAIModels({
    onSuccess: (data) => {
      if (data.models.length > 0) {
        setAvailableModels(data.models);
      }
    },
  });

  if (!isPlatformAdmin) {
    return <p className="text-muted-foreground text-sm">{t("ai.adminOnlyPlatform")}</p>;
  }

  if (settingsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("ai.loading")}</p>;
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const payload: PlatformAISettingsUpdate = {
      enabled: formState.enabled,
      provider: formState.provider || null,
      base_url: formState.baseUrl || null,
      model: formState.model || null,
      allow_guild_override: formState.allowGuildOverride,
      allow_user_override: formState.allowUserOverride,
    };
    if (formState.apiKey) {
      payload.api_key = formState.apiKey;
    }
    updateMutation.mutate(payload);
  };

  const handleTestConnection = () => {
    if (!formState.provider) return;
    testMutation.mutate({
      provider: formState.provider,
      api_key: formState.apiKey || null,
      base_url: formState.baseUrl || null,
      model: formState.model || null,
    });
  };

  const handleFetchModels = () => {
    if (!formState.provider || fetchModelsMutation.isPending) return;
    fetchModelsMutation.mutate({
      provider: formState.provider,
      api_key: formState.apiKey || null,
      base_url: formState.baseUrl || null,
    });
  };

  const getModelOptions = () => getModelsForProvider(formState.provider, availableModels);

  const providerConfig = formState.provider ? PROVIDER_CONFIGS[formState.provider] : null;
  const showApiKeyField = providerConfig?.requiresApiKey ?? false;
  const showBaseUrlField = providerConfig?.requiresBaseUrl ?? false;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("ai.title")}</CardTitle>
        <CardDescription>{t("platformAI.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("ai.enableAI")}</p>
              <p className="text-muted-foreground text-sm">{t("ai.enableAIPlatformDescription")}</p>
            </div>
            <Switch
              checked={formState.enabled}
              onCheckedChange={(checked) =>
                setFormState((prev) => ({ ...prev, enabled: Boolean(checked) }))
              }
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ai-provider">{t("ai.providerFieldLabel")}</Label>
            <Select
              value={formState.provider}
              onValueChange={(value) => {
                const config = PROVIDER_CONFIGS[value as AIProvider];
                setFormState((prev) => ({
                  ...prev,
                  provider: value as AIProvider,
                  baseUrl: config?.defaultBaseUrl ?? "",
                }));
                setAvailableModels([]);
              }}
            >
              <SelectTrigger id="ai-provider">
                <SelectValue placeholder={t("ai.providerPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {(
                  Object.entries(PROVIDER_CONFIGS) as [
                    AIProvider,
                    (typeof PROVIDER_CONFIGS)[AIProvider],
                  ][]
                ).map(([key, config]) => (
                  <SelectItem key={key} value={key}>
                    {config.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {showApiKeyField && (
            <div className="space-y-2">
              <Label htmlFor="ai-api-key">{t("ai.apiKeyLabel")}</Label>
              <Input
                id="ai-api-key"
                type="password"
                value={formState.apiKey}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, apiKey: event.target.value }))
                }
                placeholder={
                  hasExistingKey
                    ? t("ai.apiKeyPlaceholderExisting")
                    : t("ai.apiKeyPlaceholderNewShort")
                }
              />
              <p className="text-muted-foreground text-xs">
                {hasExistingKey ? t("ai.apiKeyHelpExistingShort") : t("ai.apiKeyHelpNewShort")}
              </p>
            </div>
          )}

          {showBaseUrlField && (
            <div className="space-y-2">
              <Label htmlFor="ai-base-url">{t("ai.baseUrlLabel")}</Label>
              <Input
                id="ai-base-url"
                value={formState.baseUrl}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, baseUrl: event.target.value }))
                }
                placeholder={providerConfig?.defaultBaseUrl ?? "https://api.example.com/v1"}
              />
            </div>
          )}

          {formState.provider && (
            <div className="space-y-2">
              <Label>{t("ai.modelLabel")}</Label>
              <ModelCombobox
                models={getModelOptions()}
                value={formState.model}
                onValueChange={(value) => setFormState((prev) => ({ ...prev, model: value }))}
                placeholder={providerConfig?.modelPlaceholder ?? "Select or type a model"}
                onOpen={handleFetchModels}
                isLoading={fetchModelsMutation.isPending}
              />
            </div>
          )}

          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("ai.allowGuildOverride")}</p>
              <p className="text-muted-foreground text-sm">
                {t("ai.allowGuildOverrideDescription")}
              </p>
            </div>
            <Switch
              checked={formState.allowGuildOverride}
              onCheckedChange={(checked) =>
                setFormState((prev) => ({ ...prev, allowGuildOverride: Boolean(checked) }))
              }
            />
          </div>

          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("ai.allowUserOverridePlatform")}</p>
              <p className="text-muted-foreground text-sm">
                {t("ai.allowUserOverridePlatformDescription")}
              </p>
            </div>
            <Switch
              checked={formState.allowUserOverride}
              onCheckedChange={(checked) =>
                setFormState((prev) => ({ ...prev, allowUserOverride: Boolean(checked) }))
              }
            />
          </div>

          <div className="flex gap-2">
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? t("ai.savingSettings") : t("ai.saveSettings")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={handleTestConnection}
              disabled={testMutation.isPending || !formState.provider}
            >
              {testMutation.isPending ? t("ai.testing") : t("ai.testConnection")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};
