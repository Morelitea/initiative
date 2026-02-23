import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { EmojiPicker } from "@/components/EmojiPicker";
import { TagPicker } from "@/components/tags";
import { useUpdateProject } from "@/hooks/useProjects";
import { useSetProjectTags } from "@/hooks/useTags";
import type {
  InitiativeRead,
  ProjectRead,
  TagSummary,
} from "@/api/generated/initiativeAPI.schemas";
import { TabsContent } from "@/components/ui/tabs";

interface ProjectSettingsDetailsTabProps {
  project: ProjectRead;
  projectId: number;
  canWriteProject: boolean;
  isAdmin: boolean;
  initiatives: InitiativeRead[] | undefined;
  initiativesError: boolean;
}

export const ProjectSettingsDetailsTab = ({
  project,
  projectId,
  canWriteProject,
  isAdmin,
  initiatives,
  initiativesError,
}: ProjectSettingsDetailsTabProps) => {
  const { t } = useTranslation("projects");

  const [selectedInitiativeId, setSelectedInitiativeId] = useState<string>("");
  const [nameText, setNameText] = useState<string>("");
  const [iconText, setIconText] = useState<string>("");
  const [identityMessage, setIdentityMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>("");
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(null);
  const [initiativeMessage, setInitiativeMessage] = useState<string | null>(null);
  const [projectTags, setProjectTags] = useState<TagSummary[]>([]);

  const setProjectTagsMutation = useSetProjectTags();

  useEffect(() => {
    if (project) {
      setSelectedInitiativeId(String(project.initiative_id));
      setNameText(project.name);
      setIconText(project.icon ?? "");
      setDescriptionText(project.description ?? "");
      setProjectTags(project.tags ?? []);
      setInitiativeMessage(null);
      setIdentityMessage(null);
      setDescriptionMessage(null);
    }
  }, [project]);

  const updateInitiativeOwnership = useUpdateProject({
    onSuccess: (data) => {
      setInitiativeMessage(t("settings.initiative.updated"));
      setSelectedInitiativeId(String(data.initiative_id));
    },
  });

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

      {isAdmin ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.initiative.title")}</CardTitle>
            <CardDescription>{t("settings.initiative.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            {initiativesError ? (
              <p className="text-destructive text-sm">{t("settings.initiative.loadError")}</p>
            ) : (
              <form
                className="flex flex-wrap items-end gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedInitiativeId) return;
                  updateInitiativeOwnership.mutate({
                    projectId: projectId,
                    data: { initiative_id: Number(selectedInitiativeId) },
                  });
                }}
              >
                <div className="min-w-[220px] flex-1">
                  <Label htmlFor="project-initiative">
                    {t("settings.initiative.owningInitiative")}
                  </Label>
                  <Select value={selectedInitiativeId} onValueChange={setSelectedInitiativeId}>
                    <SelectTrigger id="project-initiative" className="mt-2">
                      <SelectValue placeholder={t("settings.initiative.selectInitiative")} />
                    </SelectTrigger>
                    <SelectContent>
                      {initiatives?.map((initiative) => (
                        <SelectItem key={initiative.id} value={String(initiative.id)}>
                          {initiative.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-2">
                  <Button type="submit" disabled={updateInitiativeOwnership.isPending}>
                    {updateInitiativeOwnership.isPending
                      ? t("settings.initiative.saving")
                      : t("settings.initiative.saveInitiative")}
                  </Button>
                  {initiativeMessage ? (
                    <p className="text-primary text-sm">{initiativeMessage}</p>
                  ) : null}
                </div>
              </form>
            )}
          </CardContent>
        </Card>
      ) : null}
    </TabsContent>
  );
};
