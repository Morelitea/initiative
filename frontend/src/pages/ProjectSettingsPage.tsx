import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useRouter } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
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
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { EmojiPicker } from "@/components/EmojiPicker";
import { useAuth } from "@/hooks/useAuth";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useGuildPath } from "@/lib/guildUrl";
import { queryClient } from "@/lib/queryClient";
import {
  Project,
  Initiative,
  ProjectPermissionLevel,
  ProjectRolePermission,
  TagSummary,
} from "@/types/api";
import { ProjectTaskStatusesManager } from "@/components/projects/ProjectTaskStatusesManager";
import { TagPicker } from "@/components/tags";
import { useSetProjectTags } from "@/hooks/useTags";

const INITIATIVES_QUERY_KEY = ["initiatives"];

interface PermissionRow {
  userId: number;
  displayName: string;
  email: string;
  level: ProjectPermissionLevel;
  isOwner: boolean;
}

export const ProjectSettingsPage = () => {
  const { projectId } = useParams({ strict: false }) as { projectId: string };
  const parsedProjectId = Number(projectId);
  const router = useRouter();
  const { user } = useAuth();
  const gp = useGuildPath();
  const { t } = useTranslation("projects");
  const [selectedInitiativeId, setSelectedInitiativeId] = useState<string>("");
  const [initiativeMessage, setInitiativeMessage] = useState<string | null>(null);
  const [nameText, setNameText] = useState<string>("");
  const [iconText, setIconText] = useState<string>("");
  const [identityMessage, setIdentityMessage] = useState<string | null>(null);
  const [descriptionText, setDescriptionText] = useState<string>("");
  const [descriptionMessage, setDescriptionMessage] = useState<string | null>(null);
  const [templateMessage, setTemplateMessage] = useState<string | null>(null);
  const [duplicateMessage, setDuplicateMessage] = useState<string | null>(null);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedNewUserId, setSelectedNewUserId] = useState<string>("");
  const [selectedNewLevel, setSelectedNewLevel] = useState<ProjectPermissionLevel>("read");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [selectedMembers, setSelectedMembers] = useState<PermissionRow[]>([]);
  const [projectTags, setProjectTags] = useState<TagSummary[]>([]);
  const [roleAccessMessage, setRoleAccessMessage] = useState<string | null>(null);
  const [roleAccessError, setRoleAccessError] = useState<string | null>(null);
  const [selectedNewRoleId, setSelectedNewRoleId] = useState<string>("");
  const [selectedNewRoleLevel, setSelectedNewRoleLevel] = useState<"read" | "write">("read");

  const setProjectTagsMutation = useSetProjectTags();

  const projectQuery = useQuery<Project>({
    queryKey: ["project", parsedProjectId],
    queryFn: async () => {
      const response = await apiClient.get<Project>(`/projects/${parsedProjectId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedProjectId),
  });

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: INITIATIVES_QUERY_KEY,
    enabled: user?.role === "admin",
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  useEffect(() => {
    if (projectQuery.data) {
      setSelectedInitiativeId(String(projectQuery.data.initiative_id));
      setNameText(projectQuery.data.name);
      setIconText(projectQuery.data.icon ?? "");
      setDescriptionText(projectQuery.data.description ?? "");
      setProjectTags(projectQuery.data.tags ?? []);
      setAccessMessage(null);
      setAccessError(null);
      setRoleAccessMessage(null);
      setRoleAccessError(null);
      setInitiativeMessage(null);
      setIdentityMessage(null);
      setDescriptionMessage(null);
      setTemplateMessage(null);
    }
  }, [projectQuery.data]);

  const updateInitiativeOwnership = useMutation({
    mutationFn: async () => {
      if (!selectedInitiativeId) {
        throw new Error("Select an initiative");
      }
      const payload = { initiative_id: Number(selectedInitiativeId) };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setInitiativeMessage(t("settings.initiative.updated"));
      setSelectedInitiativeId(String(data.initiative_id));
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const updateIdentity = useMutation({
    mutationFn: async () => {
      const trimmedIcon = iconText.trim();
      const payload = {
        name: nameText.trim() || projectQuery.data?.name || "",
        icon: trimmedIcon ? trimmedIcon : null,
      };
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, payload);
      return response.data;
    },
    onSuccess: (data) => {
      setIdentityMessage(t("settings.details.detailsUpdated"));
      setNameText(data.name);
      setIconText(data.icon ?? "");
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const archiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/archive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const unarchiveProject = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/projects/${parsedProjectId}/unarchive`, {});
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const updateDescription = useMutation({
    mutationFn: async () => {
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, {
        description: descriptionText,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDescriptionMessage(t("settings.details.descriptionUpdated"));
      setDescriptionText(data.description ?? "");
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const duplicateProject = useMutation({
    mutationFn: async (name?: string) => {
      const response = await apiClient.post<Project>(`/projects/${parsedProjectId}/duplicate`, {
        name: name?.trim() || undefined,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setDuplicateMessage(t("settings.duplicate.duplicated"));
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["project", data.id] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
      router.navigate({ to: gp(`/projects/${data.id}`) });
    },
  });

  const toggleTemplateStatus = useMutation({
    mutationFn: async (nextStatus: boolean) => {
      const response = await apiClient.patch<Project>(`/projects/${parsedProjectId}`, {
        is_template: nextStatus,
      });
      return response.data;
    },
    onSuccess: (data, nextStatus) => {
      setTemplateMessage(
        nextStatus
          ? t("settings.templateStatus.markedAsTemplate")
          : t("settings.templateStatus.removedFromTemplates")
      );
      void queryClient.invalidateQueries({
        queryKey: ["project", parsedProjectId],
      });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
    },
  });

  const deleteProject = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/projects/${parsedProjectId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({
        queryKey: ["projects", "templates"],
      });
      router.navigate({ to: "/" });
    },
  });

  const addMember = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: ProjectPermissionLevel }) => {
      await apiClient.post(`/projects/${parsedProjectId}/members`, {
        user_id: userId,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.access.granted"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.grantError"));
    },
  });

  const updateMemberLevel = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: ProjectPermissionLevel }) => {
      await apiClient.patch(`/projects/${parsedProjectId}/members/${userId}`, {
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.access.updated"));
      setAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.updateError"));
    },
  });

  const removeMember = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/projects/${parsedProjectId}/members/${userId}`);
    },
    onSuccess: () => {
      setAccessMessage(t("settings.access.removed"));
      setAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.removeError"));
    },
  });

  const addAllMembers = useMutation({
    mutationFn: async (level: ProjectPermissionLevel) => {
      const userIds = availableMembers.map((member) => member.user.id);
      await apiClient.post(`/projects/${parsedProjectId}/members/bulk`, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.access.grantedAll"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.grantAllError"));
    },
  });

  const bulkUpdateLevel = useMutation({
    mutationFn: async ({
      userIds,
      level,
    }: {
      userIds: number[];
      level: ProjectPermissionLevel;
    }) => {
      await apiClient.post(`/projects/${parsedProjectId}/members/bulk`, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.access.bulkUpdated"));
      setAccessError(null);
      setSelectedMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.bulkUpdateError"));
    },
  });

  const bulkRemoveMembers = useMutation({
    mutationFn: async (userIds: number[]) => {
      await apiClient.post(`/projects/${parsedProjectId}/members/bulk-delete`, {
        user_ids: userIds,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.access.bulkRemoved"));
      setAccessError(null);
      setSelectedMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.access.bulkRemoveError"));
    },
  });

  const project = projectQuery.data;

  const initiativeRolesQuery = useInitiativeRoles(project?.initiative_id ?? null);

  const addRolePermission = useMutation({
    mutationFn: async ({ roleId, level }: { roleId: number; level: "read" | "write" }) => {
      await apiClient.post(`/projects/${parsedProjectId}/role-permissions`, {
        initiative_role_id: roleId,
        level,
      });
    },
    onSuccess: () => {
      setRoleAccessMessage(t("settings.roleAccess.granted"));
      setRoleAccessError(null);
      setSelectedNewRoleId("");
      setSelectedNewRoleLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: () => {
      setRoleAccessMessage(null);
      setRoleAccessError(t("settings.roleAccess.grantError"));
    },
  });

  const updateRolePermission = useMutation({
    mutationFn: async ({ roleId, level }: { roleId: number; level: "read" | "write" }) => {
      await apiClient.patch(`/projects/${parsedProjectId}/role-permissions/${roleId}`, {
        level,
      });
    },
    onSuccess: () => {
      setRoleAccessMessage(t("settings.roleAccess.updated"));
      setRoleAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: () => {
      setRoleAccessMessage(null);
      setRoleAccessError(t("settings.roleAccess.updateError"));
    },
  });

  const removeRolePermission = useMutation({
    mutationFn: async (roleId: number) => {
      await apiClient.delete(`/projects/${parsedProjectId}/role-permissions/${roleId}`);
    },
    onSuccess: () => {
      setRoleAccessMessage(t("settings.roleAccess.removed"));
      setRoleAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["project", parsedProjectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: () => {
      setRoleAccessMessage(null);
      setRoleAccessError(t("settings.roleAccess.removeError"));
    },
  });

  // Initiative roles not yet assigned to this project
  const availableRoles = useMemo(
    () =>
      (initiativeRolesQuery.data ?? []).filter(
        (role) => !(project?.role_permissions ?? []).some((rp) => rp.initiative_role_id === role.id)
      ),
    [initiativeRolesQuery.data, project?.role_permissions]
  );

  // Column definitions for role permissions table
  const rolePermissionColumns: ColumnDef<ProjectRolePermission>[] = useMemo(
    () => [
      {
        accessorKey: "role_display_name",
        header: t("settings.roleAccess.roleNameColumn"),
        cell: ({ row }) => <span className="font-medium">{row.original.role_display_name}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.roleAccess.accessLevelColumn"),
        cell: ({ row }) => (
          <Select
            value={row.original.level}
            onValueChange={(value) => {
              setRoleAccessMessage(null);
              setRoleAccessError(null);
              updateRolePermission.mutate({
                roleId: row.original.initiative_role_id,
                level: value as "read" | "write",
              });
            }}
            disabled={updateRolePermission.isPending}
          >
            <SelectTrigger className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">{t("settings.roleAccess.canView")}</SelectItem>
              <SelectItem value="write">{t("settings.roleAccess.canEdit")}</SelectItem>
            </SelectContent>
          </Select>
        ),
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.roleAccess.actionsColumn")}</div>,
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => {
                setRoleAccessMessage(null);
                setRoleAccessError(null);
                removeRolePermission.mutate(row.original.initiative_role_id);
              }}
              disabled={removeRolePermission.isPending}
            >
              {t("settings.roleAccess.remove")}
            </Button>
          </div>
        ),
      },
    ],
    [updateRolePermission, removeRolePermission, t]
  );

  const initiativeMembers = useMemo(
    () => project?.initiative?.members ?? [],
    [project?.initiative?.members]
  );

  // Build permission rows with user info
  const permissionRows: PermissionRow[] = useMemo(
    () =>
      (project?.permissions ?? []).map((permission) => {
        const member = initiativeMembers.find((entry) => entry.user?.id === permission.user_id);
        const ownerInfo = project?.owner;
        const displayName =
          member?.user?.full_name?.trim() ||
          member?.user?.email ||
          (permission.user_id === project?.owner_id
            ? ownerInfo?.full_name?.trim() || ownerInfo?.email || "Project owner"
            : `User ${permission.user_id}`);
        const email =
          member?.user?.email ||
          (permission.user_id === project?.owner_id ? ownerInfo?.email || "" : "");
        return {
          userId: permission.user_id,
          displayName,
          email,
          level: permission.level,
          isOwner: permission.user_id === project?.owner_id,
        };
      }),
    [project?.permissions, project?.owner, project?.owner_id, initiativeMembers]
  );

  // Column definitions for the permissions table
  const permissionColumns: ColumnDef<PermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: t("settings.access.nameColumn"),
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "email",
        header: t("settings.access.emailColumn"),
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.access.accessColumn"),
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return (
              <span className="text-muted-foreground">{t("settings.access.permissionOwner")}</span>
            );
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) => {
                setAccessMessage(null);
                setAccessError(null);
                updateMemberLevel.mutate({
                  userId: row.original.userId,
                  level: value as ProjectPermissionLevel,
                });
              }}
              disabled={updateMemberLevel.isPending}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("settings.access.permissionRead")}</SelectItem>
                <SelectItem value="write">{t("settings.access.permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.access.actionsColumn")}</div>,
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <div className="text-muted-foreground text-right text-xs">-</div>;
          }
          return (
            <div className="text-right">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() => {
                  setAccessMessage(null);
                  setAccessError(null);
                  removeMember.mutate(row.original.userId);
                }}
                disabled={removeMember.isPending}
              >
                {t("settings.access.remove")}
              </Button>
            </div>
          );
        },
      },
    ],
    [updateMemberLevel, removeMember, t]
  );

  // Initiative members who don't have permissions yet
  const availableMembers = useMemo(
    () =>
      initiativeMembers.filter(
        (member) =>
          member.user &&
          !(project?.permissions ?? []).some((permission) => permission.user_id === member.user.id)
      ),
    [initiativeMembers, project?.permissions]
  );

  if (!Number.isFinite(parsedProjectId)) {
    return <p className="text-destructive">{t("detail.invalidProjectId")}</p>;
  }

  const initiativesLoading = user?.role === "admin" ? initiativesQuery.isLoading : false;

  if (projectQuery.isLoading || initiativesLoading) {
    return <p className="text-muted-foreground text-sm">{t("settings.loading")}</p>;
  }

  if (projectQuery.isError || !project) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{t("settings.loadError")}</p>
        <Button asChild variant="link" className="px-0">
          <Link to={gp("/projects")}>{t("settings.backToProjects")}</Link>
        </Button>
      </div>
    );
  }

  const isOwner = project.owner_id === user?.id;
  const myLevel = project.my_permission_level;
  // Pure DAC: write access requires owner or write permission level
  const hasWriteAccess = myLevel === "owner" || myLevel === "write";
  // Pure DAC: write permission grants access to manage settings
  const canManageTaskStatuses = hasWriteAccess;
  const canManageAccess = hasWriteAccess;
  const canWriteProject = hasWriteAccess;

  if (!canManageAccess && !canWriteProject) {
    return (
      <div className="space-y-4">
        <Button asChild variant="link" className="px-0">
          <Link to={gp(`/projects/${project.id}`)}>{t("settings.backToProject")}</Link>
        </Button>
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>{t("settings.title")}</CardTitle>
            <CardDescription>{t("settings.noPermission")}</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const projectDisplayName = project.icon ? `${project.icon} ${project.name}` : project.name;

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {project.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/initiatives/${project.initiative.id}`)}>
                    {project.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/projects/${project.id}`)}>{project.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumbSettings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="text-muted-foreground">
          {t("settings.description", { name: projectDisplayName })}
        </p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("settings.tabDetails")}</TabsTrigger>
          {canManageAccess ? (
            <TabsTrigger value="access">{t("settings.tabAccess")}</TabsTrigger>
          ) : null}
          <TabsTrigger value="task-statuses">{t("settings.tabTaskStatuses")}</TabsTrigger>
          <TabsTrigger value="advanced">{t("settings.tabAdvanced")}</TabsTrigger>
        </TabsList>

        {/* ── Details tab ── */}
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
                      updateIdentity.mutate();
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
                        <p className="text-destructive text-sm">
                          {t("settings.details.updateError")}
                        </p>
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
                  <h3 className="text-base font-medium">
                    {t("settings.details.descriptionHeading")}
                  </h3>
                  <p className="text-muted-foreground text-sm">
                    {t("settings.details.descriptionDescription")}
                  </p>
                </div>
                {canWriteProject ? (
                  <form
                    className="space-y-4"
                    onSubmit={(event) => {
                      event.preventDefault();
                      updateDescription.mutate();
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
                        projectId: parsedProjectId,
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

          {user?.role === "admin" ? (
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>{t("settings.initiative.title")}</CardTitle>
                <CardDescription>{t("settings.initiative.description")}</CardDescription>
              </CardHeader>
              <CardContent>
                {initiativesQuery.isError ? (
                  <p className="text-destructive text-sm">{t("settings.initiative.loadError")}</p>
                ) : (
                  <form
                    className="flex flex-wrap items-end gap-3"
                    onSubmit={(event) => {
                      event.preventDefault();
                      updateInitiativeOwnership.mutate();
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
                          {initiativesQuery.data?.map((initiative) => (
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

        {/* ── Access tab ── */}
        {canManageAccess ? (
          <TabsContent value="access" className="space-y-6">
            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>{t("settings.roleAccess.title")}</CardTitle>
                <CardDescription>{t("settings.roleAccess.description")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {(project.role_permissions ?? []).length > 0 ? (
                  <DataTable
                    columns={rolePermissionColumns}
                    data={project.role_permissions ?? []}
                    getRowId={(row) => String(row.initiative_role_id)}
                  />
                ) : (
                  <p className="text-muted-foreground text-sm">
                    {t("settings.roleAccess.noRoles")}
                  </p>
                )}

                <div className="space-y-2 pt-2">
                  <Label>{t("settings.roleAccess.addRole")}</Label>
                  {initiativeRolesQuery.isLoading ? (
                    <p className="text-muted-foreground text-sm">
                      {t("settings.roleAccess.loadingRoles")}
                    </p>
                  ) : availableRoles.length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      {t("settings.roleAccess.allRolesAssigned")}
                    </p>
                  ) : (
                    <form
                      className="flex flex-wrap items-end gap-3"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!selectedNewRoleId) {
                          setRoleAccessError(t("settings.roleAccess.selectRoleError"));
                          return;
                        }
                        setRoleAccessError(null);
                        addRolePermission.mutate({
                          roleId: Number(selectedNewRoleId),
                          level: selectedNewRoleLevel,
                        });
                      }}
                    >
                      <Select value={selectedNewRoleId} onValueChange={setSelectedNewRoleId}>
                        <SelectTrigger className="min-w-[200px]">
                          <SelectValue placeholder={t("settings.roleAccess.selectRole")} />
                        </SelectTrigger>
                        <SelectContent>
                          {availableRoles.map((role) => (
                            <SelectItem key={role.id} value={String(role.id)}>
                              {role.display_name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Select
                        value={selectedNewRoleLevel}
                        onValueChange={(value) =>
                          setSelectedNewRoleLevel(value as "read" | "write")
                        }
                      >
                        <SelectTrigger className="w-[130px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="read">{t("settings.roleAccess.canView")}</SelectItem>
                          <SelectItem value="write">{t("settings.roleAccess.canEdit")}</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button type="submit" disabled={addRolePermission.isPending}>
                        {addRolePermission.isPending
                          ? t("settings.roleAccess.adding")
                          : t("settings.roleAccess.add")}
                      </Button>
                    </form>
                  )}
                  {roleAccessMessage ? (
                    <p className="text-primary text-sm">{roleAccessMessage}</p>
                  ) : null}
                  {roleAccessError ? (
                    <p className="text-destructive text-sm">{roleAccessError}</p>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card className="shadow-sm">
              <CardHeader>
                <CardTitle>{t("settings.access.title")}</CardTitle>
                <CardDescription>{t("settings.access.description")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Bulk action bar */}
                {selectedMembers.length > 0 && (
                  <div className="bg-muted flex items-center gap-3 rounded-md p-3">
                    <span className="text-sm font-medium">
                      {t("settings.access.selected", { count: selectedMembers.length })}
                    </span>
                    <Select
                      onValueChange={(level) => {
                        const userIds = selectedMembers
                          .filter((m) => !m.isOwner)
                          .map((m) => m.userId);
                        if (userIds.length > 0) {
                          bulkUpdateLevel.mutate({
                            userIds,
                            level: level as ProjectPermissionLevel,
                          });
                        }
                      }}
                      disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
                    >
                      <SelectTrigger className="w-[150px]">
                        <SelectValue placeholder={t("settings.access.changeAccess")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("settings.access.permissionRead")}</SelectItem>
                        <SelectItem value="write">
                          {t("settings.access.permissionWrite")}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      onClick={() => {
                        const userIds = selectedMembers
                          .filter((m) => !m.isOwner)
                          .map((m) => m.userId);
                        if (userIds.length > 0) {
                          bulkRemoveMembers.mutate(userIds);
                        }
                      }}
                      disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
                    >
                      {bulkRemoveMembers.isPending
                        ? t("settings.access.removing")
                        : t("settings.access.remove")}
                    </Button>
                  </div>
                )}

                {/* Access table */}
                <DataTable
                  columns={permissionColumns}
                  data={permissionRows}
                  enablePagination
                  enableFilterInput
                  filterInputColumnKey="displayName"
                  filterInputPlaceholder={t("settings.access.filterByName")}
                  enableRowSelection
                  onRowSelectionChange={setSelectedMembers}
                  onExitSelection={() => setSelectedMembers([])}
                  getRowId={(row) => String(row.userId)}
                />

                {/* Add member form */}
                <div className="space-y-2 pt-2">
                  <Label>{t("settings.access.grantAccess")}</Label>
                  {availableMembers.length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      {t("settings.access.allMembersHaveAccess")}
                    </p>
                  ) : (
                    <form
                      className="flex flex-wrap items-end gap-3"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!selectedNewUserId) {
                          setAccessError(t("settings.access.selectMemberError"));
                          return;
                        }
                        setAccessError(null);
                        addMember.mutate({
                          userId: Number(selectedNewUserId),
                          level: selectedNewLevel,
                        });
                      }}
                    >
                      <SearchableCombobox
                        items={availableMembers.map((member) => ({
                          value: String(member.user.id),
                          label: member.user.full_name?.trim() || member.user.email,
                        }))}
                        value={selectedNewUserId}
                        onValueChange={setSelectedNewUserId}
                        placeholder={t("settings.access.selectMember")}
                        emptyMessage={t("settings.access.noMembersFound")}
                        className="min-w-[200px]"
                      />
                      <Select
                        value={selectedNewLevel}
                        onValueChange={(value) =>
                          setSelectedNewLevel(value as ProjectPermissionLevel)
                        }
                      >
                        <SelectTrigger className="w-[130px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="read">
                            {t("settings.access.permissionRead")}
                          </SelectItem>
                          <SelectItem value="write">
                            {t("settings.access.permissionWrite")}
                          </SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        type="submit"
                        disabled={addMember.isPending || addAllMembers.isPending}
                      >
                        {addMember.isPending
                          ? t("settings.access.adding")
                          : t("settings.access.add")}
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => addAllMembers.mutate(selectedNewLevel)}
                        disabled={addMember.isPending || addAllMembers.isPending}
                      >
                        {addAllMembers.isPending
                          ? t("settings.access.addingAll")
                          : t("settings.access.addAll", { count: availableMembers.length })}
                      </Button>
                    </form>
                  )}
                  {accessMessage ? <p className="text-primary text-sm">{accessMessage}</p> : null}
                  {accessError ? <p className="text-destructive text-sm">{accessError}</p> : null}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        ) : null}

        {/* ── Task statuses tab ── */}
        <TabsContent value="task-statuses">
          <ProjectTaskStatusesManager
            projectId={project.id}
            canManage={Boolean(canManageTaskStatuses)}
          />
        </TabsContent>

        {/* ── Advanced tab ── */}
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
                    toggleTemplateStatus.mutate(!project.is_template);
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
                    duplicateProject.mutate(newName);
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
                    project.is_archived ? unarchiveProject.mutate() : archiveProject.mutate()
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
      </Tabs>

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title={t("settings.danger.deleteTitle")}
        description={t("settings.danger.deleteDescription")}
        confirmLabel={t("settings.danger.deleteConfirm")}
        onConfirm={() => {
          deleteProject.mutate();
          setShowDeleteConfirm(false);
        }}
        isLoading={deleteProject.isPending}
        destructive
      />
    </div>
  );
};
