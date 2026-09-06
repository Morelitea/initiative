/**
 * `/settings` — what a tool entity is called, what it is tagged with, and
 * whether it carries a comment thread.
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSetToolComments } from "@/hooks/useToolComments";
import { useSetToolTags } from "@/hooks/useToolTags";
import { toast } from "@/lib/chesterToast";

export const ToolSettingsDetailsPage = () => {
  const { t } = useTranslation("common");
  const { tool, entity, canManage, update, detailsExtra } = useToolSettings();

  const [nameValue, setNameValue] = useState(entity.name);
  const [descriptionValue, setDescriptionValue] = useState(entity.description ?? "");
  const [tags, setTags] = useState<TagSummary[]>(entity.tags ?? []);
  const [commentsEnabled, setCommentsEnabled] = useState(entity.comments_enabled);

  useEffect(() => {
    setNameValue(entity.name);
    setDescriptionValue(entity.description ?? "");
    setTags(entity.tags ?? []);
    setCommentsEnabled(entity.comments_enabled);
  }, [entity]);

  const setToolTags = useSetToolTags(tool);
  const setToolComments = useSetToolComments(tool);

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

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>{t("toolSettings.comments")}</CardTitle>
            <CardDescription>{t("toolSettings.commentsDescription")}</CardDescription>
          </div>
          <Switch
            id="tool-settings-comments-enabled"
            checked={commentsEnabled}
            onCheckedChange={(value) => {
              // Saved on flip rather than behind the Save button above, like
              // the tag picker: the switch shows the new state immediately and
              // puts the old one back if the write fails.
              const previous = commentsEnabled;
              setCommentsEnabled(value);
              setToolComments.mutate(
                { id: entity.id, enabled: value },
                { onError: () => setCommentsEnabled(previous) }
              );
            }}
            disabled={!canManage || setToolComments.isPending}
            aria-label={t("toolSettings.commentsToggle")}
          />
        </CardHeader>
      </Card>
    </div>
  );
};
