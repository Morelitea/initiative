import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AIConnectionCreate,
  AIConnectionResponse,
  AIConnectionUpdate,
  AIProvider,
} from "@/api/generated/initiativeAPI.schemas";
import { getModelsForProvider, PROVIDER_CONFIGS } from "@/lib/ai-providers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

import type { ConnectionMutations } from "./aiConnection.types";

export interface AIConnectionFormState {
  label: string;
  provider: AIProvider | "";
  baseUrl: string;
  model: string;
  apiKey: string;
  enabled: boolean;
  isDefault: boolean;
  allowMemberKeys: boolean;
}

const emptyForm: AIConnectionFormState = {
  label: "",
  provider: "",
  baseUrl: "",
  model: "",
  apiKey: "",
  enabled: true,
  isDefault: false,
  allowMemberKeys: true,
};

const toFormState = (connection: AIConnectionResponse): AIConnectionFormState => ({
  label: connection.label,
  provider: connection.provider,
  baseUrl: connection.base_url ?? "",
  model: connection.model ?? "",
  apiKey: "",
  enabled: connection.enabled,
  isDefault: connection.is_default,
  allowMemberKeys: connection.allow_member_keys,
});

interface UseAIConnectionFormArgs {
  open: boolean;
  connection: AIConnectionResponse | null;
  mutations: ConnectionMutations;
  onClose: () => void;
}

/**
 * Owns the create/edit connection form: field state, provider-derived field
 * visibility, model fetching, and submit wiring. The dialog stays presentational.
 */
export const useAIConnectionForm = ({
  open,
  connection,
  mutations,
  onClose,
}: UseAIConnectionFormArgs) => {
  const { t } = useTranslation("settings");
  const isEdit = connection !== null;
  const [form, setForm] = useState<AIConnectionFormState>(
    connection ? toFormState(connection) : emptyForm
  );
  const [availableModels, setAvailableModels] = useState<string[]>([]);

  // Reset each time the dialog is (re)opened for a given connection.
  useEffect(() => {
    if (open) {
      setForm(connection ? toFormState(connection) : emptyForm);
      setAvailableModels([]);
    }
  }, [open, connection]);

  const setField = <K extends keyof AIConnectionFormState>(
    key: K,
    value: AIConnectionFormState[K]
  ) => setForm((prev) => ({ ...prev, [key]: value }));

  const providerConfig = form.provider ? PROVIDER_CONFIGS[form.provider] : null;
  // A connection's key is EITHER shared (admin-set) OR member-supplied. When
  // members bring their own key, there is no shared-key field.
  const showApiKeyField = (providerConfig?.requiresApiKey ?? false) && !form.allowMemberKeys;
  const showBaseUrlField = providerConfig?.requiresBaseUrl ?? false;
  const modelOptions = getModelsForProvider(form.provider, availableModels);

  const changeProvider = (value: string) => {
    if (!value) return;
    const config = PROVIDER_CONFIGS[value as AIProvider];
    setForm((prev) => ({
      ...prev,
      provider: value as AIProvider,
      baseUrl: config?.defaultBaseUrl ?? "",
    }));
    setAvailableModels([]);
  };

  const fetchModels = () => {
    // Models come from a live connection, so only existing (edit) rows can
    // populate the dropdown; new connections use the provider defaults.
    if (!isEdit || !connection || mutations.fetchModels.isPending) return;
    mutations.fetchModels.mutate(connection.id, {
      onSuccess: (data) => {
        if (data.models.length > 0) setAvailableModels(data.models);
      },
    });
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form.provider) return;
    const baseUrl = showBaseUrlField ? form.baseUrl || null : null;

    if (isEdit && connection) {
      const payload: AIConnectionUpdate = {
        label: form.label,
        provider: form.provider,
        base_url: baseUrl,
        model: form.model || null,
        enabled: form.enabled,
        is_default: form.isDefault,
        allow_member_keys: form.allowMemberKeys,
      };
      // XOR: never send a shared key when members bring their own.
      if (form.apiKey && !form.allowMemberKeys) payload.api_key = form.apiKey;
      mutations.update.mutate(
        { connectionId: connection.id, data: payload },
        {
          onSuccess: () => {
            toast.success(t("aiConnections.updated"));
            onClose();
          },
          onError: (error) =>
            toast.error(getErrorMessage(error, "settings:aiConnections.saveError")),
        }
      );
      return;
    }

    const payload: AIConnectionCreate = {
      label: form.label,
      provider: form.provider,
      base_url: baseUrl,
      model: form.model || null,
      // XOR: a shared key only when members don't bring their own.
      api_key: form.allowMemberKeys ? null : form.apiKey || null,
      enabled: form.enabled,
      is_default: form.isDefault,
      allow_member_keys: form.allowMemberKeys,
    };
    mutations.create.mutate(payload, {
      onSuccess: () => {
        toast.success(t("aiConnections.created"));
        onClose();
      },
      onError: (error) => toast.error(getErrorMessage(error, "settings:aiConnections.saveError")),
    });
  };

  const isPending = isEdit ? mutations.update.isPending : mutations.create.isPending;

  return {
    form,
    setField,
    isEdit,
    providerConfig,
    showApiKeyField,
    showBaseUrlField,
    modelOptions,
    isFetchingModels: mutations.fetchModels.isPending,
    isPending,
    changeProvider,
    fetchModels,
    submit,
  };
};
