import { useTranslation } from "react-i18next";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { TabsContent } from "@/components/ui/tabs";
import { TagPicker } from "@/components/tags";
import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";

interface DocumentSettingsDetailsTabProps {
  isTemplate: boolean;
  onTemplateToggle: (value: boolean) => void;
  templateToggleDisabled: boolean;
  hasWriteAccess: boolean;
  documentTags: TagSummary[];
  onTagsChange: (newTags: TagSummary[]) => void;
}

export const DocumentSettingsDetailsTab = ({
  isTemplate,
  onTemplateToggle,
  templateToggleDisabled,
  hasWriteAccess,
  documentTags,
  onTagsChange,
}: DocumentSettingsDetailsTabProps) => {
  const { t } = useTranslation(["documents", "common"]);

  return (
    <TabsContent value="details" className="space-y-6">
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

      <Card>
        <CardHeader>
          <CardTitle>{t("settings.tagsTitle")}</CardTitle>
          <CardDescription>{t("settings.tagsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {hasWriteAccess ? (
            <TagPicker selectedTags={documentTags} onChange={onTagsChange} />
          ) : (
            <p className="text-muted-foreground text-sm">{t("settings.tagsNoAccess")}</p>
          )}
        </CardContent>
      </Card>
    </TabsContent>
  );
};
