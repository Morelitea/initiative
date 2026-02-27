import { FormEvent, useEffect, useState } from "react";
import { Link, Navigate, useParams, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useGuildPath } from "@/lib/guildUrl";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useInitiatives, useUpdateInitiative, useDeleteInitiative } from "@/hooks/useInitiatives";
import { useGuilds } from "@/hooks/useGuilds";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import type {
  InitiativeMemberRead,
  InitiativeRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { InitiativeSettingsDetailsTab } from "@/components/initiatives/settings/InitiativeSettingsDetailsTab";
import { InitiativeSettingsMembersTab } from "@/components/initiatives/settings/InitiativeSettingsMembersTab";
import { InitiativeSettingsRolesTab } from "@/components/initiatives/settings/InitiativeSettingsRolesTab";
import { InitiativeSettingsDangerTab } from "@/components/initiatives/settings/InitiativeSettingsDangerTab";
import { InitiativeSettingsDialogs } from "@/components/initiatives/settings/InitiativeSettingsDialogs";

const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativeSettingsPage = () => {
  const { initiativeId: initiativeIdParam } = useParams({ strict: false }) as {
    initiativeId: string;
  };
  const parsedInitiativeId = Number(initiativeIdParam);
  const hasValidInitiativeId = Number.isFinite(parsedInitiativeId);
  const initiativeId = hasValidInitiativeId ? parsedInitiativeId : 0;
  const router = useRouter();

  const { t } = useTranslation(["initiatives", "common"]);
  const { user } = useAuth();
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const gp = useGuildPath();

  const adminLabel = getRoleLabel("admin", roleLabels);

  const initiativesQuery = useInitiatives({ enabled: hasValidInitiativeId });

  const initiative =
    hasValidInitiativeId && initiativesQuery.data
      ? (initiativesQuery.data.find((item) => item.id === initiativeId) ?? null)
      : null;

  // Fetch roles for this initiative
  const rolesQuery = useInitiativeRoles(initiativeId || null);

  const isGuildAdmin = activeGuild?.role === "admin";
  const initiativeMembership = initiative?.members.find((member) => member.user.id === user?.id);
  const isInitiativeManager =
    initiativeMembership?.is_manager || initiativeMembership?.role === "project_manager";
  const canManageMembers = Boolean(isGuildAdmin || isInitiativeManager);
  const canDeleteInitiative = Boolean(isGuildAdmin);

  const [name, setName] = useState(initiative?.name ?? "");
  const [description, setDescription] = useState(initiative?.description ?? "");
  const [color, setColor] = useState(initiative?.color ?? DEFAULT_INITIATIVE_COLOR);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // New role dialog state
  const [showNewRoleDialog, setShowNewRoleDialog] = useState(false);

  // Delete role confirmation
  const [roleToDelete, setRoleToDelete] = useState<InitiativeRoleRead | null>(null);

  // Rename role dialog
  const [roleToRename, setRoleToRename] = useState<InitiativeRoleRead | null>(null);

  // Remove member confirmation
  const [memberToRemove, setMemberToRemove] = useState<InitiativeMemberRead | null>(null);

  useEffect(() => {
    if (initiative) {
      setName(initiative.name);
      setDescription(initiative.description ?? "");
      setColor(initiative.color ?? DEFAULT_INITIATIVE_COLOR);
    }
  }, [initiative]);

  // Set default role_id when roles load
  useEffect(() => {
    if (rolesQuery.data && !selectedRoleId) {
      const memberRole = rolesQuery.data.find((r) => r.name === "member");
      if (memberRole) {
        setSelectedRoleId(String(memberRole.id));
      }
    }
  }, [rolesQuery.data, selectedRoleId]);

  const updateInitiative = useUpdateInitiative({
    onSuccess: () => {
      toast.success(t("settings.updated"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.updateError");
      toast.error(message);
    },
  });

  const deleteInitiative = useDeleteInitiative({
    onSuccess: () => {
      toast.success(t("settings.deleted"));
      router.navigate({ to: gp("/initiatives") });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.deleteError");
      toast.error(message);
    },
  });

  const handleSaveDetails = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("settings.nameRequired"));
      return;
    }
    updateInitiative.mutate({
      initiativeId,
      data: {
        name: trimmedName,
        description: description.trim() || undefined,
        color,
      },
    });
  };

  const handleToggleQueues = (value: boolean) => {
    updateInitiative.mutate({
      initiativeId,
      data: { queues_enabled: value },
    });
  };

  const handleDeleteInitiative = () => {
    if (initiative?.is_default) {
      return;
    }
    setShowDeleteConfirm(true);
  };

  const confirmDeleteInitiative = () => {
    deleteInitiative.mutate(initiativeId);
    setShowDeleteConfirm(false);
  };

  if (!hasValidInitiativeId) {
    return <Navigate to={gp("/initiatives")} replace />;
  }

  if (initiativesQuery.isLoading || !initiativesQuery.data) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("settings.loadingInitiative")}
      </div>
    );
  }

  if (!initiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp("/initiatives")}>{t("settings.backToInitiatives")}</Link>
        </Button>
        <div className="rounded-lg border p-6">
          <h1 className="text-3xl font-semibold tracking-tight">{t("settings.notFound")}</h1>
          <p className="text-muted-foreground">{t("settings.notFoundDescription")}</p>
        </div>
      </div>
    );
  }

  if (!canManageMembers && !canDeleteInitiative) {
    return (
      <div className="space-y-4">
        <Button variant="link" size="sm" asChild className="px-0">
          <Link to={gp(`/initiatives/${initiative.id}`)}>{t("settings.backToInitiative")}</Link>
        </Button>
        <Card>
          <CardHeader>
            <CardTitle>{t("settings.permissionRequired")}</CardTitle>
            <CardDescription>{t("settings.permissionRequiredDescription")}</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/initiatives/${initiative.id}`)}>{initiative.name}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumbSettings")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">{t("settings.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("settings.subtitle")}</p>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("settings.detailsTab")}</TabsTrigger>
          <TabsTrigger value="members">{t("settings.membersTab")}</TabsTrigger>
          <TabsTrigger value="roles">{t("settings.rolesTab")}</TabsTrigger>
          <TabsTrigger value="danger">{t("settings.dangerTab")}</TabsTrigger>
        </TabsList>
        <InitiativeSettingsDetailsTab
          name={name}
          setName={setName}
          description={description}
          setDescription={setDescription}
          color={color}
          setColor={setColor}
          queuesEnabled={initiative?.queues_enabled ?? false}
          onToggleQueues={handleToggleQueues}
          canManageMembers={canManageMembers}
          isSaving={updateInitiative.isPending}
          onSaveDetails={handleSaveDetails}
        />

        <InitiativeSettingsMembersTab
          initiativeId={initiativeId}
          members={initiative.members}
          roles={rolesQuery.data}
          canManageMembers={canManageMembers}
          activeGuildId={activeGuild?.id}
          selectedUserId={selectedUserId}
          setSelectedUserId={setSelectedUserId}
          selectedRoleId={selectedRoleId}
          setSelectedRoleId={setSelectedRoleId}
          onRemoveMember={setMemberToRemove}
        />

        <InitiativeSettingsRolesTab
          initiativeId={initiativeId}
          canManageMembers={canManageMembers}
          onOpenCreateRoleDialog={() => setShowNewRoleDialog(true)}
          onDeleteRole={setRoleToDelete}
          onRenameRole={(role) => {
            setRoleToRename(role);
          }}
        />

        <InitiativeSettingsDangerTab
          isDefault={initiative.is_default}
          canDeleteInitiative={canDeleteInitiative}
          isDeleting={deleteInitiative.isPending}
          adminLabel={adminLabel}
          onDeleteInitiative={handleDeleteInitiative}
        />
      </Tabs>

      <InitiativeSettingsDialogs
        initiativeId={initiativeId}
        initiativeName={initiative.name}
        showDeleteConfirm={showDeleteConfirm}
        setShowDeleteConfirm={setShowDeleteConfirm}
        isDeletingInitiative={deleteInitiative.isPending}
        onConfirmDeleteInitiative={confirmDeleteInitiative}
        showNewRoleDialog={showNewRoleDialog}
        setShowNewRoleDialog={setShowNewRoleDialog}
        roleToDelete={roleToDelete}
        setRoleToDelete={setRoleToDelete}
        roleToRename={roleToRename}
        setRoleToRename={setRoleToRename}
        memberToRemove={memberToRemove}
        setMemberToRemove={setMemberToRemove}
      />
    </div>
  );
};
