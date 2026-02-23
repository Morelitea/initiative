import { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";

interface InitiativeSettingsDetailsTabProps {
  name: string;
  setName: (value: string) => void;
  description: string;
  setDescription: (value: string) => void;
  color: string;
  setColor: (value: string) => void;
  canManageMembers: boolean;
  isSaving: boolean;
  onSaveDetails: (event: FormEvent<HTMLFormElement>) => void;
}

export const InitiativeSettingsDetailsTab = ({
  name,
  setName,
  description,
  setDescription,
  color,
  setColor,
  canManageMembers,
  isSaving,
  onSaveDetails,
}: InitiativeSettingsDetailsTabProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  return (
    <TabsContent value="details">
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.detailsTitle")}</CardTitle>
          <CardDescription>{t("settings.detailsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={onSaveDetails}>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="initiative-name">{t("settings.nameLabel")}</Label>
                <Input
                  id="initiative-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  disabled={!canManageMembers || isSaving}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="initiative-color">{t("settings.colorLabel")}</Label>
                <ColorPickerPopover
                  id="initiative-color"
                  value={color}
                  onChange={setColor}
                  disabled={!canManageMembers || isSaving}
                  triggerLabel="Adjust"
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="initiative-description">{t("settings.descriptionLabel")}</Label>
              <Textarea
                id="initiative-description"
                rows={4}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder={t("settings.descriptionPlaceholder")}
                disabled={!canManageMembers || isSaving}
              />
            </div>
            {canManageMembers ? (
              <Button type="submit" disabled={isSaving}>
                {isSaving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t("settings.saving")}
                  </>
                ) : (
                  t("settings.saveChanges")
                )}
              </Button>
            ) : (
              <p className="text-muted-foreground text-sm">{t("settings.editPermissionNote")}</p>
            )}
          </form>
        </CardContent>
      </Card>
    </TabsContent>
  );
};
