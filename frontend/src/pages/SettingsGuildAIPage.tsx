import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  updateGuildAiSettingsApiV1SettingsAiGuildPut,
  testAiConnectionApiV1SettingsAiTestPost,
  fetchAiModelsApiV1SettingsAiModelsPost,
} from "@/api/generated/ai-settings/ai-settings";
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
import { useGuildAISettings } from "@/hooks/useAISettings";
import { useGuilds } from "@/hooks/useGuilds";
import { getModelsForProvider, PROVIDER_CONFIGS } from "@/lib/ai-providers";
import type {
  AIModelsResponse,
  AIProvider,
  AITestConnectionResponse,
  GuildAISettings,
  GuildAISettingsUpdate,
} from "@/types/api";

interface FormState {
  enabled: boolean | null;
  provider: AIProvider | "";
  apiKey: string;
  baseUrl: string;
  model: string;
  allowUserOverride: boolean | null;
  useInheritedSettings: boolean;
}

const DEFAULT_STATE: FormState = {
  enabled: null,
  provider: "",
  apiKey: "",
  baseUrl: "",
  model: "",
  allowUserOverride: null,
  useInheritedSettings: true,
};

export const SettingsGuildAIPage = () => {
  const { t } = useTranslation("settings");
  const { activeGuild, activeGuildId } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";
  const guildId = activeGuildId;
  const [formState, setFormState] = useState<FormState>(DEFAULT_STATE);
  const [hasExistingKey, setHasExistingKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  const settingsQuery = useGuildAISettings(guildId, { enabled: isGuildAdmin });

  useEffect(() => {
    if (settingsQuery.data) {
      const data = settingsQuery.data;
      const hasOwnSettings =
        data.enabled !== null ||
        data.provider !== null ||
        data.has_api_key ||
        data.base_url !== null ||
        data.model !== null;

      setFormState({
        enabled: data.enabled ?? null,
        provider: data.provider ?? "",
        apiKey: "",
        baseUrl: data.base_url ?? "",
        model: data.model ?? "",
        allowUserOverride: data.allow_user_override ?? null,
        useInheritedSettings: !hasOwnSettings,
      });
      setHasExistingKey(data.has_api_key);
    }
  }, [settingsQuery.data]);

  const updateMutation = useMutation({
    mutationFn: async (payload: GuildAISettingsUpdate) => {
      return updateGuildAiSettingsApiV1SettingsAiGuildPut(
        payload as Parameters<typeof updateGuildAiSettingsApiV1SettingsAiGuildPut>[0]
      ) as unknown as Promise<GuildAISettings>;
    },
    onSuccess: (data) => {
      toast.success(t("guildAI.saveSuccess"));
      setFormState((prev) => ({ ...prev, apiKey: "" }));
      setHasExistingKey(data.has_api_key);
      void settingsQuery.refetch();
    },
    onError: (error: Error & { response?: { status?: number; data?: { detail?: string } } }) => {
      const message = error.response?.data?.detail ?? t("ai.saveError");
      toast.error(message);
    },
  });

  const testMutation = useMutation({
    mutationFn: async () => {
      const provider = formState.useInheritedSettings
        ? settingsQuery.data?.effective_provider
        : formState.provider;
      if (!provider) {
        throw new Error("No provider selected");
      }
      return testAiConnectionApiV1SettingsAiTestPost({
        provider: provider,
        api_key: formState.apiKey || null,
        base_url: formState.useInheritedSettings
          ? settingsQuery.data?.effective_base_url
          : formState.baseUrl || null,
        model: formState.useInheritedSettings
          ? settingsQuery.data?.effective_model
          : formState.model || null,
      } as Parameters<
        typeof testAiConnectionApiV1SettingsAiTestPost
      >[0]) as unknown as Promise<AITestConnectionResponse>;
    },
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

  const fetchModelsMutation = useMutation({
    mutationFn: async () => {
      const provider = formState.useInheritedSettings
        ? settingsQuery.data?.effective_provider
        : formState.provider;
      if (!provider) {
        throw new Error("No provider selected");
      }
      return fetchAiModelsApiV1SettingsAiModelsPost({
        provider: provider,
        api_key: formState.apiKey || null,
        base_url: formState.useInheritedSettings
          ? settingsQuery.data?.effective_base_url
          : formState.baseUrl || null,
      } as Parameters<
        typeof fetchAiModelsApiV1SettingsAiModelsPost
      >[0]) as unknown as Promise<AIModelsResponse>;
    },
    onSuccess: (data) => {
      if (data.models.length > 0) {
        setAvailableModels(data.models);
      }
    },
  });

  if (!isGuildAdmin) {
    return <p className="text-muted-foreground text-sm">{t("ai.adminOnlyGuild")}</p>;
  }

  if (settingsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("ai.loading")}</p>;
  }

  if (settingsQuery.isError) {
    return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
  }

  if (!settingsQuery.data) {
    return <p className="text-muted-foreground text-sm">{t("ai.noSettings")}</p>;
  }

  if (!settingsQuery.data.can_override) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("ai.title")}</CardTitle>
          <CardDescription>{t("ai.managedByPlatform")}</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">{t("ai.adminDisabledGuild")}</p>
          <div className="mt-4 space-y-2">
            <p className="text-sm">
              <span className="font-medium">{t("ai.statusLabel")}</span>{" "}
              {settingsQuery.data.effective_enabled ? t("ai.enabled") : t("ai.disabled")}
            </p>
            {settingsQuery.data.effective_provider && (
              <p className="text-sm">
                <span className="font-medium">{t("ai.providerLabel")}</span>{" "}
                {settingsQuery.data.effective_provider}
              </p>
            )}
            {settingsQuery.data.effective_model && (
              <p className="text-sm">
                <span className="font-medium">{t("ai.modelLabel")}</span>{" "}
                {settingsQuery.data.effective_model}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    );
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (formState.useInheritedSettings) {
      updateMutation.mutate({ clear_settings: true });
      return;
    }

    const payload: GuildAISettingsUpdate = {
      enabled: formState.enabled,
      provider: formState.provider || null,
      base_url: formState.baseUrl || null,
      model: formState.model || null,
      allow_user_override: formState.allowUserOverride,
    };
    if (formState.apiKey) {
      payload.api_key = formState.apiKey;
    }
    updateMutation.mutate(payload);
  };

  const activeProvider = formState.useInheritedSettings
    ? settingsQuery.data?.effective_provider
    : formState.provider;
  const getModelOptions = () => getModelsForProvider(activeProvider ?? "", availableModels);

  const providerConfig = activeProvider ? PROVIDER_CONFIGS[activeProvider] : null;
  const showApiKeyField = providerConfig?.requiresApiKey ?? false;
  const showBaseUrlField = providerConfig?.requiresBaseUrl ?? false;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("guildAI.title")}</CardTitle>
        <CardDescription>{t("guildAI.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("ai.usePlatformSettings")}</p>
              <p className="text-muted-foreground text-sm">
                {t("ai.usePlatformSettingsDescription")}
              </p>
            </div>
            <Switch
              checked={formState.useInheritedSettings}
              onCheckedChange={(checked) => {
                const useInherited = Boolean(checked);
                if (useInherited) {
                  // Switching to inherited - clear custom values
                  setFormState((prev) => ({ ...prev, useInheritedSettings: true }));
                } else {
                  // Switching to custom - initialize with effective values
                  setFormState((prev) => ({
                    ...prev,
                    useInheritedSettings: false,
                    enabled: settingsQuery.data?.effective_enabled ?? false,
                    provider: settingsQuery.data?.effective_provider ?? "",
                    baseUrl: settingsQuery.data?.effective_base_url ?? "",
                    model: settingsQuery.data?.effective_model ?? "",
                  }));
                }
              }}
            />
          </div>

          {formState.useInheritedSettings && (
            <div className="bg-muted/50 rounded-md border p-4">
              <p className="text-muted-foreground mb-2 text-sm font-medium">
                {t("ai.inheritedSettings")}
              </p>
              <div className="space-y-1 text-sm">
                <p>
                  <span className="font-medium">{t("ai.statusLabel")}</span>{" "}
                  {settingsQuery.data.effective_enabled ? t("ai.enabled") : t("ai.disabled")}
                </p>
                {settingsQuery.data.effective_provider && (
                  <p>
                    <span className="font-medium">{t("ai.providerLabel")}</span>{" "}
                    {settingsQuery.data.effective_provider}
                  </p>
                )}
                {settingsQuery.data.effective_model && (
                  <p>
                    <span className="font-medium">{t("ai.modelLabel")}</span>{" "}
                    {settingsQuery.data.effective_model}
                  </p>
                )}
              </div>
            </div>
          )}

          {!formState.useInheritedSettings && (
            <>
              <div className="flex items-center justify-between rounded-md border px-4 py-3">
                <div>
                  <p className="font-medium">{t("ai.enableAI")}</p>
                  <p className="text-muted-foreground text-sm">
                    {t("ai.enableAIGuildDescription")}
                  </p>
                </div>
                <Switch
                  checked={formState.enabled ?? false}
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

              {activeProvider && (
                <div className="space-y-2">
                  <Label>{t("ai.modelLabel")}</Label>
                  <ModelCombobox
                    models={getModelOptions()}
                    value={formState.model}
                    onValueChange={(value) => setFormState((prev) => ({ ...prev, model: value }))}
                    placeholder={providerConfig?.modelPlaceholder ?? "Select or type a model"}
                    onOpen={() => {
                      if (activeProvider && !fetchModelsMutation.isPending) {
                        fetchModelsMutation.mutate();
                      }
                    }}
                    isLoading={fetchModelsMutation.isPending}
                  />
                </div>
              )}

              <div className="flex items-center justify-between rounded-md border px-4 py-3">
                <div>
                  <p className="font-medium">{t("ai.allowUserOverride")}</p>
                  <p className="text-muted-foreground text-sm">
                    {t("ai.allowUserOverrideDescription")}
                  </p>
                </div>
                <Switch
                  checked={formState.allowUserOverride ?? true}
                  onCheckedChange={(checked) =>
                    setFormState((prev) => ({ ...prev, allowUserOverride: Boolean(checked) }))
                  }
                />
              </div>
            </>
          )}

          <div className="flex gap-2">
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? t("ai.savingSettings") : t("ai.saveSettings")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => testMutation.mutate()}
              disabled={
                testMutation.isPending || (!formState.useInheritedSettings && !activeProvider)
              }
            >
              {testMutation.isPending ? t("ai.testing") : t("ai.testConnection")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};
