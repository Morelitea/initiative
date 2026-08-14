import { useTranslation } from "react-i18next";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

interface DocumentSettingsDetailsTabProps {
  isTemplate: boolean;
  onTemplateToggle: (value: boolean) => void;
  templateToggleDisabled: boolean;
}

export const DocumentSettingsDetailsTab = ({
  isTemplate,
  onTemplateToggle,
  templateToggleDisabled,
}: DocumentSettingsDetailsTabProps) => {
  const { t } = useTranslation(["documents", "common"]);

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>{t("settings.templateTitle")}</CardTitle>
            <CardDescription>{t("settings.templateDescription")}</CardDescription>
          </div>
          <Switch
            id="document-template-toggle"
            checked={isTemplate}
            onCheckedChange={onTemplateToggle}
            disabled={templateToggleDisabled}
            aria-label={t("settings.templateToggle")}
          />
        </CardHeader>
      </Card>
    </>
  );
};
