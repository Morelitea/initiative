import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { EmojiPicker } from "@/components/EmojiPicker";
import { ProjectDateFields } from "@/components/projects/ProjectDateFields";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateProject } from "@/hooks/useProjects";
import { useServerForm } from "@/hooks/useServerForm";
import { dateRangeBounds } from "@/lib/dateRange";

interface ProjectSettingsDetailsTabProps {
  project: ProjectRead;
  projectId: number;
  canWriteProject: boolean;
}

/** The fields this form owns, as one saveable unit. */
interface ProjectDetailsValue {
  name: string;
  icon: string;
  description: string;
  startDate: string;
  endDate: string;
}

const detailsFromProject = (project: ProjectRead | undefined): ProjectDetailsValue => ({
  name: project?.name ?? "",
  icon: project?.icon ?? "",
  description: project?.description ?? "",
  startDate: project?.start_date ?? "",
  endDate: project?.end_date ?? "",
});

export const ProjectSettingsDetailsTab = ({
  project,
  projectId,
  canWriteProject,
}: ProjectSettingsDetailsTabProps) => {
  const { t } = useTranslation("projects");

  // One save writes every field here, so the form keeps following the project
  // — picking up whatever somebody else changed — until there is unsaved
  // typing of our own, which wins until it is saved or the tab moves on.
  const form = useServerForm(project, detailsFromProject, project?.id);
  const {
    name: nameText,
    icon: iconText,
    description: descriptionText,
    startDate,
    endDate,
  } = form.values;
  const setNameText = (next: string) => form.set({ name: next });
  const setIconText = (next: string) => form.set({ icon: next });
  const setDescriptionText = (next: string) => form.set({ description: next });
  const setStartDate = (next: string) => form.set({ startDate: next });
  const setEndDate = (next: string) => form.set({ endDate: next });
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const updateProject = useUpdateProject(projectId, {
    onSuccess: (data) => {
      setSavedMessage(t("settings.details.detailsUpdated"));
      form.settle(detailsFromProject(data));
    },
  });

  const { isInverted: datesInverted } = dateRangeBounds(startDate, endDate);

  return (
    <>
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("settings.details.title")}</CardTitle>
          <CardDescription>{t("settings.details.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-8">
          {canWriteProject ? (
            <form
              className="space-y-8"
              onSubmit={(event) => {
                event.preventDefault();
                if (datesInverted) {
                  return;
                }
                setSavedMessage(null);
                const trimmedIcon = iconText.trim();
                updateProject.mutate({
                  name: nameText.trim() || project.name || "",
                  icon: trimmedIcon || null,
                  description: descriptionText,
                  // "" means "no date" in the picker; the API clears on null.
                  start_date: startDate || null,
                  end_date: endDate || null,
                });
              }}
            >
              <div className="space-y-3">
                <div className="space-y-1">
                  <h3 className="font-medium text-base">{t("settings.details.identityHeading")}</h3>
                  <p className="text-muted-foreground text-sm">
                    {t("settings.details.identityDescription")}
                  </p>
                </div>
                <div className="flex flex-col gap-4 md:flex-row md:items-start">
                  <div className="w-full space-y-2 md:max-w-xs">
                    <Label htmlFor="project-icon">{t("settings.details.iconLabel")}</Label>
                    <EmojiPicker
                      id="project-icon"
                      value={iconText || undefined}
                      onChange={(emoji) => setIconText(emoji ?? "")}
                    />
                    <p className="text-muted-foreground text-sm">
                      {t("settings.details.iconHint")}
                    </p>
                  </div>
                  <div className="w-full flex-1 space-y-2">
                    <Label htmlFor="project-name">{t("settings.details.nameLabel")}</Label>
                    <Input
                      id="project-name"
                      value={nameText}
                      onChange={(event) => setNameText(event.target.value)}
                      placeholder={t("settings.details.namePlaceholder")}
                      required
                    />
                  </div>
                </div>
              </div>

              <div className="h-px bg-border" />

              <div className="space-y-3">
                <div className="space-y-1">
                  <h3 className="font-medium text-base">
                    {t("settings.details.descriptionHeading")}
                  </h3>
                  <p className="text-muted-foreground text-sm">
                    {t("settings.details.descriptionDescription")}
                  </p>
                </div>
                <Textarea
                  rows={4}
                  value={descriptionText}
                  onChange={(event) => setDescriptionText(event.target.value)}
                  placeholder={t("settings.details.descriptionPlaceholder")}
                />
              </div>

              <div className="h-px bg-border" />

              <div className="space-y-3">
                <div className="space-y-1">
                  <h3 className="font-medium text-base">{t("settings.details.scheduleHeading")}</h3>
                  <p className="text-muted-foreground text-sm">
                    {t("settings.details.scheduleDescription")}
                  </p>
                </div>
                <ProjectDateFields
                  idPrefix="project-settings"
                  startDate={startDate}
                  endDate={endDate}
                  onStartDateChange={setStartDate}
                  onEndDateChange={setEndDate}
                />
              </div>

              <div className="flex flex-col gap-2">
                <Button type="submit" disabled={updateProject.isPending || datesInverted}>
                  {updateProject.isPending
                    ? t("settings.details.saving")
                    : t("settings.details.saveDetails")}
                </Button>
                {savedMessage ? <p className="text-primary text-sm">{savedMessage}</p> : null}
                {updateProject.isError ? (
                  <p className="text-destructive text-sm">{t("settings.details.updateError")}</p>
                ) : null}
              </div>
            </form>
          ) : (
            <p className="text-muted-foreground text-sm">{t("settings.details.noWriteAccess")}</p>
          )}
        </CardContent>
      </Card>
    </>
  );
};
