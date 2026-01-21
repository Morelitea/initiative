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
import { useAuth } from "@/hooks/useAuth";
import { getModelsForProvider, PROVIDER_CONFIGS } from "@/lib/ai-providers";
import type {
  AIModelsResponse,
  AIProvider,
  AITestConnectionResponse,
  PlatformAISettings,
  PlatformAISettingsUpdate,
} from "@/types/api";

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
  const { user } = useAuth();
  const isSuperUser = user?.id === 1;
  const [formState, setFormState] = useState<FormState>(DEFAULT_STATE);
  const [hasExistingKey, setHasExistingKey] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  const settingsQuery = useQuery<PlatformAISettings>({
    queryKey: ["settings", "ai", "platform"],
    enabled: isSuperUser,
    queryFn: async () => {
      const response = await apiClient.get<PlatformAISettings>("/settings/ai/platform");
      return response.data;
    },
  });

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

  const updateMutation = useMutation({
    mutationFn: async (payload: PlatformAISettingsUpdate) => {
      const response = await apiClient.put<PlatformAISettings>("/settings/ai/platform", payload);
      return response.data;
    },
    onSuccess: (data) => {
      toast.success("AI settings saved");
      setFormState((prev) => ({ ...prev, apiKey: "" }));
      setHasExistingKey(data.has_api_key);
      void settingsQuery.refetch();
    },
    onError: () => toast.error("Unable to save AI settings"),
  });

  const testMutation = useMutation({
    mutationFn: async () => {
      if (!formState.provider) {
        throw new Error("No provider selected");
      }
      const response = await apiClient.post<AITestConnectionResponse>("/settings/ai/test", {
        provider: formState.provider,
        api_key: formState.apiKey || null,
        base_url: formState.baseUrl || null,
        model: formState.model || null,
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
      if (!formState.provider) {
        throw new Error("No provider selected");
      }
      const response = await apiClient.post<AIModelsResponse>("/settings/ai/models", {
        provider: formState.provider,
        api_key: formState.apiKey || null,
        base_url: formState.baseUrl || null,
      });
      return response.data;
    },
    onSuccess: (data) => {
      if (data.models.length > 0) {
        setAvailableModels(data.models);
      }
    },
  });

  if (!isSuperUser) {
    return (
      <p className="text-muted-foreground text-sm">
        Only the initial super user can manage platform AI settings.
      </p>
    );
  }

  if (settingsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading AI settings...</p>;
  }

  if (settingsQuery.isError || !settingsQuery.data) {
    return <p className="text-destructive text-sm">Unable to load AI settings.</p>;
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

  const getModelOptions = () => getModelsForProvider(formState.provider, availableModels);

  const providerConfig = formState.provider ? PROVIDER_CONFIGS[formState.provider] : null;
  const showApiKeyField = providerConfig?.requiresApiKey ?? false;
  const showBaseUrlField = providerConfig?.requiresBaseUrl ?? false;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>AI Configuration</CardTitle>
        <CardDescription>
          Configure AI provider settings for the platform. Users can bring their own API keys if
          allowed.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-6" onSubmit={handleSubmit}>
          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">Enable AI features</p>
              <p className="text-muted-foreground text-sm">
                Allow AI-powered features across the platform.
              </p>
            </div>
            <Switch
              checked={formState.enabled}
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
                placeholder={hasExistingKey ? "••••••••" : "Enter API key"}
              />
              <p className="text-muted-foreground text-xs">
                {hasExistingKey
                  ? "Leave blank to keep the existing key."
                  : "Enter your API key for this provider."}
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

          {formState.provider && (
            <div className="space-y-2">
              <Label>Model</Label>
              <ModelCombobox
                models={getModelOptions()}
                value={formState.model}
                onValueChange={(value) => setFormState((prev) => ({ ...prev, model: value }))}
                placeholder={providerConfig?.modelPlaceholder ?? "Select or type a model"}
                onOpen={() => {
                  if (formState.provider && !fetchModelsMutation.isPending) {
                    fetchModelsMutation.mutate();
                  }
                }}
                isLoading={fetchModelsMutation.isPending}
              />
            </div>
          )}

          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">Allow guild override</p>
              <p className="text-muted-foreground text-sm">
                Let guild administrators configure their own AI settings.
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
              <p className="font-medium">Allow user override</p>
              <p className="text-muted-foreground text-sm">
                Let users configure their own AI settings (BYOK).
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
              {updateMutation.isPending ? "Saving..." : "Save settings"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending || !formState.provider}
            >
              {testMutation.isPending ? "Testing..." : "Test Connection"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};
