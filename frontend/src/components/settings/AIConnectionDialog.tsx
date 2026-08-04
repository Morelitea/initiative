import { useTranslation } from "react-i18next";

import type {
  AIConnectionResponse,
  AIProvider,
  ConnectionScope,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { PROVIDER_CONFIGS } from "@/lib/ai-providers";

import type { ConnectionMutations } from "./aiConnection.types";
import { useAIConnectionForm } from "./useAIConnectionForm";

interface AIConnectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scope: ConnectionScope;
  providers: AIProvider[];
  connection: AIConnectionResponse | null;
  mutations: ConnectionMutations;
}

export const AIConnectionDialog = ({
  open,
  onOpenChange,
  scope,
  providers,
  connection,
  mutations,
}: AIConnectionDialogProps) => {
  const { t } = useTranslation("settings");
  const {
    form,
    setField,
    isEdit,
    providerConfig,
    showApiKeyField,
    showBaseUrlField,
    modelOptions,
    isFetchingModels,
    isPending,
    changeProvider,
    fetchModels,
    submit,
  } = useAIConnectionForm({
    open,
    connection,
    mutations,
    onClose: () => onOpenChange(false),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t("aiConnections.editTitle") : t("aiConnections.newTitle")}
          </DialogTitle>
          <DialogDescription>
            {scope === "platform"
              ? t("aiConnections.platformDialogDescription")
              : t("aiConnections.guildDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <form className="space-y-4" onSubmit={submit}>
          <div className="space-y-2">
            <Label htmlFor="ai-connection-label">{t("aiConnections.labelLabel")}</Label>
            <Input
              id="ai-connection-label"
              value={form.label}
              required
              onChange={(event) => setField("label", event.target.value)}
              placeholder={t("aiConnections.labelPlaceholder")}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ai-connection-provider">{t("ai.providerFieldLabel")}</Label>
            <Select value={form.provider} onValueChange={changeProvider}>
              <SelectTrigger id="ai-connection-provider">
                <SelectValue placeholder={t("ai.providerPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {providers.map((key) => (
                  <SelectItem key={key} value={key}>
                    {PROVIDER_CONFIGS[key].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between rounded-md border px-4 py-3">
              <div>
                <p className="font-medium">{t("aiConnections.allowMemberKeysLabel")}</p>
                <p className="text-muted-foreground text-sm">
                  {t("aiConnections.allowMemberKeysDescription")}
                </p>
              </div>
              <Switch
                checked={form.allowMemberKeys}
                onCheckedChange={(checked) => setField("allowMemberKeys", Boolean(checked))}
              />
            </div>
          </div>

          {showApiKeyField && (
            <div className="space-y-2">
              <Label htmlFor="ai-connection-key">{t("ai.apiKeyLabel")}</Label>
              <Input
                id="ai-connection-key"
                type="password"
                value={form.apiKey}
                onChange={(event) => setField("apiKey", event.target.value)}
                placeholder={
                  connection?.has_api_key
                    ? t("aiConnections.apiKeyPlaceholderExisting")
                    : t("aiConnections.apiKeyPlaceholderNew")
                }
              />
              <p className="text-muted-foreground text-xs">
                {connection?.has_api_key
                  ? t("aiConnections.apiKeyHelpExisting")
                  : t("aiConnections.apiKeyHelpNew")}
              </p>
            </div>
          )}

          {showBaseUrlField && (
            <div className="space-y-2">
              <Label htmlFor="ai-connection-base-url">{t("ai.baseUrlLabel")}</Label>
              <Input
                id="ai-connection-base-url"
                value={form.baseUrl}
                onChange={(event) => setField("baseUrl", event.target.value)}
                placeholder={providerConfig?.defaultBaseUrl ?? "https://api.example.com/v1"}
              />
              {form.provider === "ollama" &&
                form.baseUrl.trim().toLowerCase().startsWith("http://") && (
                  <p className="text-sm text-yellow-600 dark:text-yellow-500">
                    {t("ai.httpWarning")}
                  </p>
                )}
            </div>
          )}

          {form.provider && (
            <div className="space-y-2">
              <Label>{t("ai.modelLabel")}</Label>
              <ModelCombobox
                models={modelOptions}
                value={form.model}
                onValueChange={(value) => setField("model", value)}
                placeholder={
                  providerConfig?.modelPlaceholder ?? t("aiConnections.modelPlaceholder")
                }
                onOpen={fetchModels}
                isLoading={isFetchingModels}
              />
            </div>
          )}

          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("aiConnections.enabledLabel")}</p>
              <p className="text-muted-foreground text-sm">
                {t("aiConnections.enabledDescription")}
              </p>
            </div>
            <Switch
              checked={form.enabled}
              onCheckedChange={(checked) => setField("enabled", Boolean(checked))}
            />
          </div>

          <div className="flex items-center justify-between rounded-md border px-4 py-3">
            <div>
              <p className="font-medium">{t("aiConnections.defaultLabel")}</p>
              <p className="text-muted-foreground text-sm">
                {t("aiConnections.defaultDescription")}
              </p>
            </div>
            <Switch
              checked={form.isDefault}
              onCheckedChange={(checked) => setField("isDefault", Boolean(checked))}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("aiConnections.cancel")}
            </Button>
            <Button type="submit" disabled={isPending || !form.provider || !form.label}>
              {isPending ? t("aiConnections.saving") : t("aiConnections.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};
