import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ProjectRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { EmojiPicker } from "@/components/EmojiPicker";
import { ProjectDateFields } from "@/components/projects/ProjectDateFields";
import { TagPicker } from "@/components/tags";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useUpdateProject } from "@/hooks/useProjects";
import { useSetToolTags } from "@/hooks/useToolTags";
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

const detailsFromProject = (project: ProjectRead): ProjectDetailsValue => ({
  name: project.name,
  icon: project.icon ?? "",
  description: project.description ?? "",
  startDate: project.start_date ?? "",
  endDate: project.end_date ?? "",
});

/** Order-stable projection of a form value, for dirty comparison. */
const serializeDetails = (value: ProjectDetailsValue): string =>
  JSON.stringify([value.name, value.icon, value.description, value.startDate, value.endDate]);

export const ProjectSettingsDetailsTab = ({
  project,
  projectId,
  canWriteProject,
}: ProjectSettingsDetailsTabProps) => {
  const { t } = useTranslation("projects");

  const [nameText, setNameText] = useState<string>("");
  const [iconText, setIconText] = useState<string>("");
  const [descriptionText, setDescriptionText] = useState<string>("");
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [projectTags, setProjectTags] = useState<TagSummary[]>([]);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  // The server values the form was last filled from. Anything that still
  // matches them is safe to replace on a refetch; anything else is the user's
  // unsaved typing.
  const [savedSnapshot, setSavedSnapshot] = useState<string | null>(null);
  const seededProjectIdRef = useRef<number | null>(null);
  const isDirtyRef = useRef(false);

  const setProjectTagsMutation = useSetToolTags(Tool.project);

  const currentSnapshot = serializeDetails({
    name: nameText,
    icon: iconText,
    description: descriptionText,
    startDate,
    endDate,
  });
  const isDirty = savedSnapshot !== null && currentSnapshot !== savedSnapshot;
  // Mirrored into a ref so the seeding effect reads the latest dirtiness
  // without taking it as a dependency.
  isDirtyRef.current = isDirty;

  useEffect(() => {
    if (!project) {
      return;
    }
    // One save writes every field here, so a stale form would revert whatever
    // someone else changed meanwhile — reseed from each refetch to pick their
    // edits up. The exception is unsaved typing of our own, which wins until
    // it is saved or the tab moves to another project.
    const isNewProject = seededProjectIdRef.current !== project.id;
    if (!isNewProject && isDirtyRef.current) {
      return;
    }
    seededProjectIdRef.current = project.id;
    const next = detailsFromProject(project);
    setNameText(next.name);
    setIconText(next.icon);
    setDescriptionText(next.description);
    setStartDate(next.startDate);
    setEndDate(next.endDate);
    setProjectTags(project.tags ?? []);
    setSavedSnapshot(serializeDetails(next));
    if (isNewProject) {
      setSavedMessage(null);
    }
  }, [project]);

  const updateProject = useUpdateProject({
    onSuccess: (data) => {
      // Re-baseline to what the server stored, so the form counts as clean
      // again and the next refetch is free to reseed it.
      const saved = detailsFromProject(data);
      setSavedMessage(t("settings.details.detailsUpdated"));
      setNameText(saved.name);
      setIconText(saved.icon);
      setDescriptionText(saved.description);
      setStartDate(saved.startDate);
      setEndDate(saved.endDate);
      setSavedSnapshot(serializeDetails(saved));
    },
  });

  const { isInverted: datesInverted } = dateRangeBounds(startDate, endDate);

  return (
    <TabsContent value="details" className="space-y-6">
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
                  projectId: projectId,
                  data: {
                    name: nameText.trim() || project.name || "",
                    icon: trimmedIcon || null,
                    description: descriptionText,
                    // "" means "no date" in the picker; the API clears on null.
                    start_date: startDate || null,
                    end_date: endDate || null,
                  },
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

          <div className="h-px bg-border" />

          {/* Tags save on pick rather than with the form — the picker commits
              each change as you make it, like the tag chips elsewhere. */}
          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="font-medium text-base">{t("settings.details.tagsHeading")}</h3>
              <p className="text-muted-foreground text-sm">
                {t("settings.details.tagsDescription")}
              </p>
            </div>
            {canWriteProject ? (
              <TagPicker
                selectedTags={projectTags}
                onChange={(newTags) => {
                  setProjectTags(newTags);
                  setProjectTagsMutation.mutate({
                    id: projectId,
                    tagIds: newTags.map((tag) => tag.id),
                  });
                }}
              />
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("settings.details.noWriteAccessTags")}
              </p>
            )}
          </div>
        </CardContent>
      </Card>
    </TabsContent>
  );
};
