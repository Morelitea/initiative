import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { AIConfigMode } from "@/api/generated/initiativeAPI.schemas";
import {
  AIConnectionManager,
  type ConnectionMutations,
} from "@/components/settings/AIConnectionManager";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  useCreatePlatformConnection,
  useDeletePlatformConnection,
  useFetchPlatformConnectionModels,
  usePlatformAIMode,
  usePlatformConnections,
  useTestPlatformConnection,
  useUpdatePlatformAIMode,
  useUpdatePlatformConnection,
} from "@/hooks/useAISettings";
import { useAuth } from "@/hooks/useAuth";
import { getProvidersForScope } from "@/lib/ai-providers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

const MODES: AIConfigMode[] = ["disabled", "platform", "guild"];

export const SettingsAIPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const isPlatformOwner = hasCapability(user, Capability.configManage);

  const modeQuery = usePlatformAIMode({ enabled: isPlatformOwner });
  const [mode, setMode] = useState<AIConfigMode>("disabled");

  useEffect(() => {
    if (modeQuery.data) {
      setMode(modeQuery.data.mode);
    }
  }, [modeQuery.data]);

  const updateMode = useUpdatePlatformAIMode({
    onSuccess: () => toast.success(t("platformAI.modeSaved")),
    onError: (error) => toast.error(getErrorMessage(error, "settings:platformAI.modeSaveError")),
  });

  const savedMode = modeQuery.data?.mode;
  const connectionsQuery = usePlatformConnections({
    enabled: isPlatformOwner && savedMode === "platform",
  });

  const mutations: ConnectionMutations = {
    create: useCreatePlatformConnection(),
    update: useUpdatePlatformConnection(),
    remove: useDeletePlatformConnection(),
    test: useTestPlatformConnection(),
    fetchModels: useFetchPlatformConnectionModels(),
  };

  if (!isPlatformOwner) {
    return <p className="text-muted-foreground text-sm">{t("platformAI.adminOnly")}</p>;
  }

  if (modeQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("ai.loading")}</p>;
  }

  if (modeQuery.isError || !modeQuery.data) {
    return <p className="text-destructive text-sm">{t("ai.loadError")}</p>;
  }

  const isDirty = mode !== modeQuery.data.mode;

  const handleSave = () => {
    updateMode.mutate({ mode });
  };

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("platformAI.title")}</CardTitle>
          <CardDescription>{t("platformAI.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <fieldset className="space-y-3">
            <legend className="font-medium text-sm">{t("platformAI.modeLabel")}</legend>
            <RadioGroup value={mode} onValueChange={(value) => setMode(value as AIConfigMode)}>
              {MODES.map((value) => (
                <Label
                  key={value}
                  htmlFor={`ai-mode-${value}`}
                  className="flex cursor-pointer items-start gap-3 rounded-md border px-4 py-3 font-normal has-[:checked]:border-primary"
                >
                  <RadioGroupItem id={`ai-mode-${value}`} value={value} className="mt-0.5" />
                  <span className="space-y-1">
                    <span className="block font-medium">{t(`platformAI.mode_${value}`)}</span>
                    <span className="block text-muted-foreground text-sm">
                      {t(`platformAI.mode_${value}_description`)}
                    </span>
                  </span>
                </Label>
              ))}
            </RadioGroup>
          </fieldset>

          <Button type="button" onClick={handleSave} disabled={updateMode.isPending || !isDirty}>
            {updateMode.isPending ? t("platformAI.savingMode") : t("platformAI.saveMode")}
          </Button>
        </CardContent>
      </Card>

      {savedMode === "platform" && (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("platformAI.connectionsTitle")}</CardTitle>
            <CardDescription>{t("platformAI.connectionsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <AIConnectionManager
              scope="platform"
              connections={connectionsQuery.data ?? []}
              isLoading={connectionsQuery.isLoading}
              isError={connectionsQuery.isError}
              providers={getProvidersForScope("platform")}
              mutations={mutations}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
};
