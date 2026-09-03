/**
 * `/settings` — what a tool entity is called, and what it is tagged with.
 *
 * The section every tool's settings open on, so it is served at `/settings`
 * itself rather than at a `/settings/details` alias.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TagPicker } from "@/components/tags";
import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useSetToolTags } from "@/hooks/useToolTags";
import { toast } from "@/lib/chesterToast";

export const ToolSettingsDetailsPage = () => {
  const { t } = useTranslation("common");
  const { tool, entity, canManage, update, detailsExtra } = useToolSettings();

  const [nameValue, setNameValue] = useState(entity.name);
  const [descriptionValue, setDescriptionValue] = useState(entity.description ?? "");
  const [tags, setTags] = useState<TagSummary[]>(entity.tags ?? []);

  useEffect(() => {
    setNameValue(entity.name);
    setDescriptionValue(entity.description ?? "");
    setTags(entity.tags ?? []);
  }, [entity]);

  const setToolTags = useSetToolTags(tool);

  const handleDetailsSave = () => {
    const trimmedName = nameValue.trim();
    if (!trimmedName) return;
    update?.mutate(
      { name: trimmedName, description: descriptionValue.trim() || null },
      { onSuccess: () => toast.success(t("toolSettings.detailsUpdated")) }
    );
  };

  return (
    <div className="space-y-6">
      {update && (
        <Card>
          <CardHeader>
            <CardTitle>{t("toolSettings.tabDetails")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="tool-settings-name">{t("name")}</Label>
              <Input
                id="tool-settings-name"
                value={nameValue}
                onChange={(e) => setNameValue(e.target.value)}
                placeholder={t("toolSettings.namePlaceholder")}
                disabled={!canManage}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="tool-settings-description">{t("description")}</Label>
              <Textarea
                id="tool-settings-description"
                value={descriptionValue}
                onChange={(e) => setDescriptionValue(e.target.value)}
                placeholder={t("toolSettings.descriptionPlaceholder")}
                disabled={!canManage}
                rows={3}
              />
            </div>
            {canManage && (
              <Button onClick={handleDetailsSave} disabled={update.isPending || !nameValue.trim()}>
                {update.isPending ? t("toolSettings.saving") : t("save")}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {detailsExtra}

      <Card>
        <CardHeader>
          <CardTitle>{t("toolSettings.tags")}</CardTitle>
          <CardDescription>{t("toolSettings.tagsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {canManage ? (
            <TagPicker
              selectedTags={tags}
              onChange={(newTags) => {
                // Tags persist on pick rather than with a Save button, so the
                // picker shows the new selection immediately and puts the old
                // one back if the write fails.
                const previous = tags;
                setTags(newTags);
                setToolTags.mutate(
                  { id: entity.id, tagIds: newTags.map((tag) => tag.id) },
                  { onError: () => setTags(previous) }
                );
              }}
            />
          ) : (
            <p className="text-muted-foreground text-sm">{t("toolSettings.tagsNoAccess")}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
};
