import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
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
import { getModelsForProvider, PROVIDER_CONFIGS } from "@/lib/ai-providers";
import type {
  AIModelsResponse,
  AIProvider,
  AITestConnectionResponse,
  UserAISettings,
  UserAISettingsUpdate,
} from "@/types/api";

interface FormState {
  enabled: boolean | null;
  provider: AIProvider | "";
  apiKey: string;
  baseUrl: string;
  model: string;
  useInheritedSettings: boolean;
}

const DEFAULT_STATE: FormState = {
  enabled: null,
  provider: "",
  apiKey: "",
  baseUrl: "",
  model: "",
  useInheritedSettings: true,
};

export const UserSettingsAIPage = () => {
  const [formState, setFormState] = useState<FormState>(DEFAULT_STATE);
  const [hasExistingKey, setHasExistingKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  const settingsQuery = useQuery<UserAISettings>({
    queryKey: ["settings", "ai", "user"],
    queryFn: async () => {
      const response = await apiClient.get<UserAISettings>("/settings/ai/user");
      return response.data;
    },
  });

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
        useInheritedSettings: !hasOwnSettings,
      });
      setHasExistingKey(data.has_api_key);
    }
  }, [settingsQuery.data]);

  const updateMutation = useMutation({
    mutationFn: async (payload: UserAISettingsUpdate) => {
      const response = await apiClient.put<UserAISettings>("/settings/ai/user", payload);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success("AI settings saved");
      setFormState((prev) => ({ ...prev, apiKey: "" }));
      setHasExistingKey(data.has_api_key);
      void settingsQuery.refetch();
    },
    onError: (error: Error & { response?: { status?: number; data?: { detail?: string } } }) => {
      const message = error.response?.data?.detail ?? "Unable to save AI settings";
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
      const response = await apiClient.post<AITestConnectionResponse>("/settings/ai/test", {
        provider: provider,
        api_key: formState.apiKey || null,
        base_url: formState.useInheritedSettings
          ? settingsQuery.data?.effective_base_url
          : formState.baseUrl || null,
        model: formState.useInheritedSettings
          ? settingsQuery.data?.effective_model
          : formState.model || null,
      });
      return response.data;
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
    onError: () => toast.error("Unable to test connection"),
  });

  const fetchModelsMutation = useMutation({
    mutationFn: async () => {
      const provider = formState.useInheritedSettings
        ? settingsQuery.data?.effective_provider
        : formState.provider;
      if (!provider) {
        throw new Error("No provider selected");
      }
      const response = await apiClient.post<AIModelsResponse>("/settings/ai/models", {
        provider: provider,
        api_key: formState.apiKey || null,
        base_url: formState.useInheritedSettings
          ? settingsQuery.data?.effective_base_url
          : formState.baseUrl || null,
      });
      return response.data;
    },
    onSuccess: (data) => {
      if (data.models.length > 0) {
        setAvailableModels(data.models);
      }
    },
  });

  if (settingsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading AI settings...</p>;
  }

  if (settingsQuery.isError) {
    return <p className="text-destructive text-sm">Unable to load AI settings.</p>;
  }

  if (!settingsQuery.data) {
    return <p className="text-muted-foreground text-sm">No AI settings available.</p>;
  }

  if (!settingsQuery.data.can_override) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>AI Configuration</CardTitle>
          <CardDescription>AI settings are managed by your administrator.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-muted-foreground text-sm">
            Your administrator has disabled user-level AI configuration. AI features are using{" "}
            {settingsQuery.data.settings_source === "guild" ? "guild" : "platform"} settings.
          </p>
          <div className="mt-4 space-y-2">
            <p className="text-sm">
              <span className="font-medium">Status:</span>{" "}
              {settingsQuery.data.effective_enabled ? "Enabled" : "Disabled"}
            </p>
            {settingsQuery.data.effective_provider && (
              <p className="text-sm">
                <span className="font-medium">Provider:</span>{" "}
                {settingsQuery.data.effective_provider}
              </p>
            )}
            {settingsQuery.data.effective_model && (
              <p className="text-sm">
                <span className="font-medium">Model:</span> {settingsQuery.data.effective_model}
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

    const payload: UserAISettingsUpdate = {
      enabled: formState.enabled,
      provider: formState.provider || null,
      base_url: formState.baseUrl || null,
      model: formState.model || null,
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

  const settingsSourceLabel =
    settingsQuery.data.settings_source === "guild"
      ? "guild"
      : settingsQuery.data.settings_source === "user"
        ? "your personal"
        : settingsQuery.data.settings_source === "mixed"
          ? "inherited"
          : "platform";

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>AI Configuration</CardTitle>
        <CardDescription>
          Configure your personal AI settings. You can use {settingsSourceLabel} defaults or bring
          your own API key (BYOK).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">Use default settings</p>
              <p className="text-muted-foreground text-sm">
                Inherit AI configuration from {settingsSourceLabel} defaults.
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
                Current {settingsSourceLabel} settings:
              </p>
              <div className="space-y-1 text-sm">
                <p>
                  <span className="font-medium">Status:</span>{" "}
                  {settingsQuery.data.effective_enabled ? "Enabled" : "Disabled"}
                </p>
                {settingsQuery.data.effective_provider && (
                  <p>
                    <span className="font-medium">Provider:</span>{" "}
                    {settingsQuery.data.effective_provider}
                  </p>
                )}
                {settingsQuery.data.effective_model && (
                  <p>
                    <span className="font-medium">Model:</span> {settingsQuery.data.effective_model}
                  </p>
                )}
              </div>
            </div>
          )}

          {!formState.useInheritedSettings && (
            <>
              <div className="flex items-center justify-between rounded-md border px-4 py-3">
                <div>
                  <p className="font-medium">Enable AI features</p>
                  <p className="text-muted-foreground text-sm">Use AI-powered features.</p>
                </div>
                <Switch
                  checked={formState.enabled ?? false}
                  onCheckedChange={(checked) =>
                    setFormState((prev) => ({ ...prev, enabled: Boolean(checked) }))
                  }
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="ai-provider">Provider</Label>
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
                    <SelectValue placeholder="Select a provider" />
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
                  <Label htmlFor="ai-api-key">API Key</Label>
                  <Input
                    id="ai-api-key"
                    type="password"
                    value={formState.apiKey}
                    onChange={(event) =>
                      setFormState((prev) => ({ ...prev, apiKey: event.target.value }))
                    }
                    placeholder={hasExistingKey ? "••••••••" : "Enter your API key"}
                  />
                  <p className="text-muted-foreground text-xs">
                    {hasExistingKey
                      ? "Leave blank to keep your existing key."
                      : "Enter your personal API key for this provider."}
                  </p>
                </div>
              )}

              {showBaseUrlField && (
                <div className="space-y-2">
                  <Label htmlFor="ai-base-url">Base URL</Label>
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
                  <Label>Model</Label>
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
            </>
          )}

          <div className="flex gap-2">
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? "Saving..." : "Save settings"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => testMutation.mutate()}
              disabled={
                testMutation.isPending || (!formState.useInheritedSettings && !activeProvider)
              }
            >
              {testMutation.isPending ? "Testing..." : "Test Connection"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};
