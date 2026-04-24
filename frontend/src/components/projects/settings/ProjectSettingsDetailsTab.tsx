import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { EmojiPicker } from "@/components/EmojiPicker";
import { TagPicker } from "@/components/tags";
import { useUpdateProject } from "@/hooks/useProjects";
import { useSetProjectTags } from "@/hooks/useTags";
import type { ProjectRead, TagSummary } from "@/api/generated/initiativeAPI.schemas";
import { TabsContent } from "@/components/ui/tabs";

interface ProjectSettingsDetailsTabProps {
  project: ProjectRead;
  projectId: number;
  canWriteProject: boolean;
}

export const ProjectSettingsDetailsTab = ({
  project,
  projectId,
  canWriteProject,
}: ProjectSettingsDetailsTabProps) => {
  const { t } = useTranslation("projects");

  const [nameText, setNameText] = useState<string>("");
  const [iconText, setIconText] = useState<string>("");
  const [identityMessage, setIdentityMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>("");
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(null);
  const [projectTags, setProjectTags] = useState<TagSummary[]>([]);

  const setProjectTagsMutation = useSetProjectTags();

  useEffect(() => {
    if (project) {
      setNameText(project.name);
      setIconText(project.icon ?? "");
      setDescriptionText(project.description ?? "");
      setProjectTags(project.tags ?? []);
      setIdentityMessage(null);
      setDescriptionMessage(null);
    }
  }, [project]);

  const updateIdentity = useUpdateProject({
    onSuccess: (data) => {
      setIdentityMessage(t("settings.details.detailsUpdated"));
      setNameText(data.name);
      setIconText(data.icon ?? "");
    },
  });

  const updateDescription = useUpdateProject({
    onSuccess: (data) => {
      setDescriptionMessage(t("settings.details.descriptionUpdated"));
      setDescriptionText(data.description ?? "");
    },
  });

  return (
    <TabsContent value="details" className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("settings.details.title")}</CardTitle>
          <CardDescription>{t("settings.details.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-8">
          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">{t("settings.details.identityHeading")}</h3>
              <p className="text-muted-foreground text-sm">
                {t("settings.details.identityDescription")}
              </p>
            </div>
            {canWriteProject ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  setIdentityMessage(null);
                  const trimmedIcon = iconText.trim();
                  updateIdentity.mutate({
                    projectId: projectId,
                    data: {
                      name: nameText.trim() || project.name || "",
                      icon: trimmedIcon || null,
                    },
                  });
                }}
              >
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
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateIdentity.isPending}>
                    {updateIdentity.isPending
                      ? t("settings.details.saving")
                      : t("settings.details.saveDetails")}
                  </Button>
                  {identityMessage ? (
                    <p className="text-primary text-sm">{identityMessage}</p>
                  ) : null}
                  {updateIdentity.isError ? (
                    <p className="text-destructive text-sm">{t("settings.details.updateError")}</p>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("settings.details.noWriteAccessIdentity")}
              </p>
            )}
          </div>

          <div className="bg-border h-px" />

          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">{t("settings.details.descriptionHeading")}</h3>
              <p className="text-muted-foreground text-sm">
                {t("settings.details.descriptionDescription")}
              </p>
            </div>
            {canWriteProject ? (
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  updateDescription.mutate({
                    projectId: projectId,
                    data: { description: descriptionText },
                  });
                }}
              >
                <Textarea
                  rows={4}
                  value={descriptionText}
                  onChange={(event) => setDescriptionText(event.target.value)}
                  placeholder={t("settings.details.descriptionPlaceholder")}
                />
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateDescription.isPending}>
                    {updateDescription.isPending
                      ? t("settings.details.saving")
                      : t("settings.details.saveDescription")}
                  </Button>
                  {descriptionMessage ? (
                    <p className="text-primary text-sm">{descriptionMessage}</p>
                  ) : null}
                </div>
              </form>
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("settings.details.noWriteAccessDescription")}
              </p>
            )}
          </div>

          <div className="bg-border h-px" />

          <div className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-base font-medium">{t("settings.details.tagsHeading")}</h3>
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
                    projectId: projectId,
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
