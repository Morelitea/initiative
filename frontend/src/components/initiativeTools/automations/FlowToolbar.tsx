import { useTranslation } from "react-i18next";
import { ArrowLeft, Save, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

interface FlowToolbarProps {
  name: string;
  onNameChange: (name: string) => void;
  onSave: () => void;
  isSaving: boolean;
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onBack: () => void;
}

export function FlowToolbar({
  name,
  onNameChange,
  onSave,
  isSaving,
  enabled,
  onEnabledChange,
  onBack,
}: FlowToolbarProps) {
  const { t } = useTranslation("automations");

  return (
    <div className="bg-card flex items-center gap-3 border-b px-4 py-2">
      {/* Left: Back button */}
      <Button variant="ghost" size="icon" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
        <span className="sr-only">{t("toolbar.back")}</span>
      </Button>

      {/* Center: Editable name */}
      <Input
        value={name}
        onChange={(e) => onNameChange(e.target.value)}
        className="focus:border-input max-w-sm border-transparent bg-transparent text-lg font-semibold"
        aria-label={t("toolbar.flowName")}
      />

      <div className="flex-1" />

      {/* Right: Enabled switch + Save */}
      <div className="flex items-center gap-2">
        <Switch id="flow-enabled" checked={enabled} onCheckedChange={onEnabledChange} />
        <Label htmlFor="flow-enabled" className="text-sm">
          {enabled ? t("toolbar.enabled") : t("toolbar.disabled")}
        </Label>
      </div>

      <Button onClick={onSave} disabled={isSaving}>
        {isSaving ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <Save className="mr-2 h-4 w-4" />
        )}
        {t("toolbar.save")}
      </Button>
    </div>
  );
}
