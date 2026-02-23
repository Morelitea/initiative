import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { TabsContent } from "@/components/ui/tabs";
import {
  useUpdateProject,
  useDeleteProject,
  useArchiveProject,
  useUnarchiveProject,
  useDuplicateProject,
} from "@/hooks/useProjects";
import { useGuildPath } from "@/lib/guildUrl";
import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { useRouter } from "@tanstack/react-router";

interface ProjectSettingsAdvancedTabProps {
  project: ProjectRead;
  projectId: number;
  canWriteProject: boolean;
  isOwner: boolean;
}

export const ProjectSettingsAdvancedTab = ({
  project,
  projectId,
  canWriteProject,
  isOwner,
}: ProjectSettingsAdvancedTabProps) => {
  const { t } = useTranslation("projects");
  const router = useRouter();
  const gp = useGuildPath();

  const [templateMessage, setTemplateMessage] = useState<string | null>(null);
  const [duplicateMessage, setDuplicateMessage] = useState<string | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const toggleTemplateStatus = useUpdateProject({
    onSuccess: (_data, vars) => {
      setTemplateMessage(
        vars.data.is_template
          ? t("settings.templateStatus.markedAsTemplate")
          : t("settings.templateStatus.removedFromTemplates")
      );
    },
  });

  const duplicateProject = useDuplicateProject({
    onSuccess: (data) => {
      setDuplicateMessage(t("settings.duplicate.duplicated"));
      router.navigate({ to: gp(`/projects/${data.id}`) });
    },
  });

  const archiveProject = useArchiveProject();

  const unarchiveProject = useUnarchiveProject();

  const deleteProject = useDeleteProject({
    onSuccess: () => {
      router.navigate({ to: "/" });
    },
  });

  return (
    <>
      <TabsContent value="advanced" className="space-y-6">
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.templateStatus.title")}</CardTitle>
            <CardDescription>{t("settings.templateStatus.description")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-muted-foreground text-sm">
              {project.is_template
                ? t("settings.templateStatus.isTemplate")
                : t("settings.templateStatus.isStandard")}
            </p>
            {templateMessage ? <p className="text-primary text-sm">{templateMessage}</p> : null}
          </CardContent>
          <CardFooter className="flex flex-wrap gap-3">
            {canWriteProject ? (
              <Button
                type="button"
                variant={project.is_template ? "outline" : "default"}
                onClick={() => {
                  setTemplateMessage(null);
                  toggleTemplateStatus.mutate({
                    projectId: projectId,
                    data: { is_template: !project.is_template },
                  });
                }}
                disabled={toggleTemplateStatus.isPending}
              >
                {project.is_template
                  ? t("settings.templateStatus.convertToStandard")
                  : t("settings.templateStatus.markAsTemplate")}
              </Button>
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("settings.templateStatus.noWriteAccess")}
              </p>
            )}
            {project.is_template ? (
              <Button asChild variant="link" className="px-0">
                <Link to={gp("/projects")}>{t("settings.templateStatus.viewAllTemplates")}</Link>
              </Button>
            ) : null}
          </CardFooter>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.duplicate.title")}</CardTitle>
            <CardDescription>{t("settings.duplicate.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            {duplicateMessage ? <p className="text-primary text-sm">{duplicateMessage}</p> : null}
          </CardContent>
          <CardFooter>
            {canWriteProject ? (
              <Button
                type="button"
                onClick={() => {
                  const defaultName = `${project.name} copy`;
                  const newName = window.prompt(t("settings.duplicate.promptName"), defaultName);
                  if (newName === null) {
                    return;
                  }
                  setDuplicateMessage(null);
                  duplicateProject.mutate({
                    projectId: projectId,
                    data: { name: newName.trim() || undefined },
                  });
                }}
                disabled={duplicateProject.isPending}
              >
                {duplicateProject.isPending
                  ? t("settings.duplicate.duplicating")
                  : t("settings.duplicate.duplicateButton")}
              </Button>
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("settings.duplicate.noWriteAccess")}
              </p>
            )}
          </CardFooter>
        </Card>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.archiveStatus.title")}</CardTitle>
            <CardDescription>
              {project.is_archived
                ? t("settings.archiveStatus.isArchived")
                : t("settings.archiveStatus.isActive")}
            </CardDescription>
          </CardHeader>
          <CardFooter>
            {canWriteProject ? (
              <Button
                type="button"
                variant="outline"
                onClick={() =>
                  project.is_archived
                    ? unarchiveProject.mutate(projectId)
                    : archiveProject.mutate(projectId)
                }
                disabled={archiveProject.isPending || unarchiveProject.isPending}
              >
                {project.is_archived
                  ? t("settings.archiveStatus.unarchive")
                  : t("settings.archiveStatus.archive")}
              </Button>
            ) : (
              <p className="text-muted-foreground text-sm">
                {t("settings.archiveStatus.noWriteAccess")}
              </p>
            )}
          </CardFooter>
        </Card>

        {isOwner ? (
          <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
            <CardHeader>
              <CardTitle className="text-destructive">{t("settings.danger.title")}</CardTitle>
              <CardDescription className="text-destructive">
                {t("settings.danger.description")}
              </CardDescription>
            </CardHeader>
            <CardFooter>
              <Button
                type="button"
                variant="destructive"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={deleteProject.isPending}
              >
                {t("settings.danger.deleteButton")}
              </Button>
            </CardFooter>
          </Card>
        ) : null}
      </TabsContent>

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t("settings.danger.deleteTitle")}
        description={t("settings.danger.deleteDescription")}
        confirmLabel={t("settings.danger.deleteConfirm")}
        onConfirm={() => {
          deleteProject.mutate(projectId);
          setShowDeleteConfirm(false);
        }}
        isLoading={deleteProject.isPending}
        destructive
      />
    </>
  );
};
