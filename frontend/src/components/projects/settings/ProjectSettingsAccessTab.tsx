import { useTranslation } from "react-i18next";

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";
import { ShareControl } from "@/components/access/ShareControl";
import { TabsContent } from "@/components/ui/tabs";
import { useSetProjectGrants } from "@/hooks/useProjects";
import { toast } from "@/lib/chesterToast";

interface ProjectSettingsAccessTabProps {
  project: ProjectRead;
  projectId: number;
}

export const ProjectSettingsAccessTab = ({ project, projectId }: ProjectSettingsAccessTabProps) => {
  const { t } = useTranslation("projects");

  const setGrants = useSetProjectGrants(projectId, {
    onSuccess: () => toast.success(t("settings.access.updated")),
  });

  const canManage = project.my_permission_level === "owner";

  return (
    <TabsContent value="access" className="space-y-4">
      <ShareControl
        initiativeId={project.initiative_id}
        grants={project.grants}
        onChange={(grants) => setGrants.mutate(grants)}
        ownerId={project.owner_id}
        disabled={!canManage || setGrants.isPending}
      />
    </TabsContent>
  );
};
