import { useEffect, useMemo, useState } from "react";
import { Link, useRouter, useParams } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { ArrowRightLeft, Copy, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

import {
  updateDocumentApiV1DocumentsDocumentIdPatch,
  deleteDocumentApiV1DocumentsDocumentIdDelete,
  duplicateDocumentApiV1DocumentsDocumentIdDuplicatePost,
  copyDocumentApiV1DocumentsDocumentIdCopyPost,
  addDocumentMemberApiV1DocumentsDocumentIdMembersPost,
  updateDocumentMemberApiV1DocumentsDocumentIdMembersUserIdPatch,
  removeDocumentMemberApiV1DocumentsDocumentIdMembersUserIdDelete,
  addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost,
  removeDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkDeletePost,
  addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost,
  updateDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdPatch,
  removeDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdDelete,
} from "@/api/generated/documents/documents";
import { invalidateAllDocuments, invalidateDocument } from "@/api/query-keys";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/hooks/useAuth";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useDocument, useSetDocumentCache } from "@/hooks/useDocuments";
import { useInitiatives } from "@/hooks/useInitiatives";
import { useGuildPath } from "@/lib/guildUrl";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type {
  DocumentRead,
  DocumentPermissionLevel,
  DocumentRolePermission,
  TagSummary,
} from "@/types/api";
import { TagPicker } from "@/components/tags";
import { useSetDocumentTags } from "@/hooks/useTags";

interface PermissionRow {
  userId: number;
  displayName: string;
  email: string;
  level: DocumentPermissionLevel;
  isOwner: boolean;
}

export const DocumentSettingsPage = () => {
  const { t } = useTranslation(["documents", "common"]);
  const dateLocale = useDateLocale();
  const { documentId } = useParams({ strict: false }) as { documentId: string };
  const parsedId = Number(documentId);
  const router = useRouter();
  const setDocumentCache = useSetDocumentCache();
  const { user } = useAuth();
  const gp = useGuildPath();

  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [copyDialogOpen, setCopyDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [duplicateTitle, setDuplicateTitle] = useState("");
  const [copyTitle, setCopyTitle] = useState("");
  const [copyInitiativeId, setCopyInitiativeId] = useState("");
  const [isTemplate, setIsTemplate] = useState(false);
  const [accessMessage, setAccessMessage] = useState<string | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [selectedNewUserId, setSelectedNewUserId] = useState<string>("");
  const [selectedNewLevel, setSelectedNewLevel] = useState<DocumentPermissionLevel>("read");
  const [selectedMembers, setSelectedMembers] = useState<PermissionRow[]>([]);
  const [documentTags, setDocumentTags] = useState<TagSummary[]>([]);
  const [selectedNewRoleId, setSelectedNewRoleId] = useState<string>("");
  const [selectedNewRoleLevel, setSelectedNewRoleLevel] = useState<"read" | "write">("read");

  const setDocumentTagsMutation = useSetDocumentTags();

  const documentQuery = useDocument(Number.isFinite(parsedId) ? parsedId : null);

  const document = documentQuery.data;

  const rolesQuery = useInitiativeRoles(document?.initiative_id ?? null);

  const initiativesQuery = useInitiatives({ enabled: Boolean(document) && Boolean(user) });

  // Pure DAC: users with write or owner permission can manage the document
  const canManageDocument = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    const myLevel = document.my_permission_level;
    return myLevel === "owner" || myLevel === "write";
  }, [document, user]);

  // Pure DAC: only owners can delete/duplicate documents
  const isOwner = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    return document.my_permission_level === "owner";
  }, [document, user]);

  // Pure DAC: check if user has write access
  const hasWriteAccess = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    const myLevel = document.my_permission_level;
    return myLevel === "owner" || myLevel === "write";
  }, [document, user]);

  const manageableInitiatives = useMemo(() => {
    const initiatives = initiativesQuery.data ?? [];
    if (!user) {
      return [];
    }
    if (user.role === "admin") {
      return initiatives;
    }
    return initiatives.filter((initiative) =>
      initiative.members.some(
        (member) => member.user.id === user.id && member.role === "project_manager"
      )
    );
  }, [initiativesQuery.data, user]);

  const copyableInitiatives = useMemo(() => {
    if (!document) {
      return [];
    }
    return manageableInitiatives.filter((initiative) => initiative.id !== document.initiative_id);
  }, [document, manageableInitiatives]);

  // Initiative members for the permission table
  const initiativeMembers = useMemo(
    () => document?.initiative?.members ?? [],
    [document?.initiative?.members]
  );

  // Build permission rows with user info
  const permissionRows: PermissionRow[] = useMemo(() => {
    const permissions = document?.permissions ?? [];
    return permissions.map((permission) => {
      const member = initiativeMembers.find((entry) => entry.user?.id === permission.user_id);
      const displayName =
        member?.user?.full_name?.trim() ||
        member?.user?.email ||
        t("bulk.userFallback", { id: permission.user_id });
      const email = member?.user?.email || "";
      return {
        userId: permission.user_id,
        displayName,
        email,
        level: permission.level,
        isOwner: permission.level === "owner",
      };
    });
  }, [document?.permissions, initiativeMembers, t]);

  useEffect(() => {
    if (!document) {
      return;
    }
    setIsTemplate(document.is_template);
    setDuplicateTitle(t("settings.duplicateTitlePlaceholder", { title: document.title }));
    setCopyTitle(document.title);
    setDocumentTags(document.tags ?? []);
    setAccessMessage(null);
    setAccessError(null);
  }, [document, t]);

  useEffect(() => {
    if (!copyDialogOpen) {
      return;
    }
    if (copyableInitiatives.length === 0) {
      setCopyInitiativeId("");
      return;
    }
    const currentIsValid = copyableInitiatives.some(
      (initiative) => String(initiative.id) === copyInitiativeId
    );
    if (!currentIsValid) {
      setCopyInitiativeId(String(copyableInitiatives[0].id));
    }
  }, [copyDialogOpen, copyableInitiatives, copyInitiativeId]);

  const addMember = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: DocumentPermissionLevel }) => {
      await addDocumentMemberApiV1DocumentsDocumentIdMembersPost(parsedId, {
        user_id: userId,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.accessGranted"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void invalidateDocument(parsedId);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.grantAccessError"));
    },
  });

  const updateMemberLevel = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: DocumentPermissionLevel }) => {
      await updateDocumentMemberApiV1DocumentsDocumentIdMembersUserIdPatch(parsedId, userId, {
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.accessUpdated"));
      setAccessError(null);
      void invalidateDocument(parsedId);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.updateAccessError"));
    },
  });

  const removeMember = useMutation({
    mutationFn: async (userId: number) => {
      await removeDocumentMemberApiV1DocumentsDocumentIdMembersUserIdDelete(parsedId, userId);
    },
    onSuccess: () => {
      setAccessMessage(t("settings.accessRemoved"));
      setAccessError(null);
      void invalidateDocument(parsedId);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.removeAccessError"));
    },
  });

  const addAllMembers = useMutation({
    mutationFn: async (level: DocumentPermissionLevel) => {
      const userIds = availableMembers.map((member) => member.user.id);
      await addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost(parsedId, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.accessGranted"));
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void invalidateDocument(parsedId);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.grantAccessError"));
    },
  });

  const bulkUpdateLevel = useMutation({
    mutationFn: async ({
      userIds,
      level,
    }: {
      userIds: number[];
      level: DocumentPermissionLevel;
    }) => {
      await addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost(parsedId, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.accessUpdated"));
      setAccessError(null);
      setSelectedMembers([]);
      void invalidateDocument(parsedId);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.updateAccessError"));
    },
  });

  const bulkRemoveMembers = useMutation({
    mutationFn: async (userIds: number[]) => {
      await removeDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkDeletePost(parsedId, {
        user_ids: userIds,
      });
    },
    onSuccess: () => {
      setAccessMessage(t("settings.accessRemoved"));
      setAccessError(null);
      setSelectedMembers([]);
      void invalidateDocument(parsedId);
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError(t("settings.removeAccessError"));
    },
  });

  const duplicateDocument = useMutation({
    mutationFn: async () => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      const trimmedTitle = duplicateTitle.trim();
      if (!trimmedTitle) {
        throw new Error("Document title is required");
      }
      return duplicateDocumentApiV1DocumentsDocumentIdDuplicatePost(document.id, {
        title: trimmedTitle,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (duplicated) => {
      toast.success(t("settings.documentDuplicated"));
      setDuplicateDialogOpen(false);
      void invalidateAllDocuments();
      router.navigate({
        to: gp(`/documents/${duplicated.id}`),
      });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.duplicateError");
      toast.error(message);
    },
  });

  const copyDocument = useMutation({
    mutationFn: async () => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      if (!copyInitiativeId) {
        throw new Error("Select a target initiative");
      }
      const trimmedTitle = copyTitle.trim();
      if (!trimmedTitle) {
        throw new Error("Document title is required");
      }
      return copyDocumentApiV1DocumentsDocumentIdCopyPost(document.id, {
        target_initiative_id: Number(copyInitiativeId),
        title: trimmedTitle,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (copied) => {
      toast.success(
        t("settings.documentCopied", {
          initiative:
            copyableInitiatives.find((i) => String(i.id) === copyInitiativeId)?.name ?? "",
        })
      );
      setCopyDialogOpen(false);
      void invalidateAllDocuments();
      router.navigate({ to: gp(`/documents/${copied.id}`) });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.copyError");
      toast.error(message);
    },
  });

  const deleteDocument = useMutation({
    mutationFn: async () => {
      await deleteDocumentApiV1DocumentsDocumentIdDelete(parsedId);
    },
    onSuccess: () => {
      toast.success(t("settings.documentDeleted"));
      void invalidateAllDocuments();
      setDeleteDialogOpen(false);
      router.navigate({ to: gp("/documents") });
    },
    onError: () => {
      toast.error(t("settings.deleteError"));
    },
  });

  const updateTemplate = useMutation({
    mutationFn: async (nextValue: boolean) => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      return updateDocumentApiV1DocumentsDocumentIdPatch(document.id, {
        is_template: nextValue,
      }) as unknown as Promise<DocumentRead>;
    },
    onSuccess: (updated) => {
      setIsTemplate(updated.is_template);
      setDocumentCache(parsedId, updated);
      void invalidateAllDocuments();
    },
    onError: () => {
      toast.error(t("settings.templateError"));
    },
  });

  // Role permission mutations
  const addRolePermission = useMutation({
    mutationFn: async ({ roleId, level }: { roleId: number; level: "read" | "write" }) => {
      await addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost(parsedId, {
        initiative_role_id: roleId,
        level,
      });
    },
    onSuccess: () => {
      toast.success(t("settings.roleAccessGranted"));
      setSelectedNewRoleId("");
      setSelectedNewRoleLevel("read");
      void invalidateDocument(parsedId);
    },
    onError: () => {
      toast.error(t("settings.grantRoleAccessError"));
    },
  });

  const updateRolePermission = useMutation({
    mutationFn: async ({ roleId, level }: { roleId: number; level: "read" | "write" }) => {
      await updateDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdPatch(
        parsedId,
        roleId,
        { level }
      );
    },
    onSuccess: () => {
      toast.success(t("settings.roleAccessUpdated"));
      void invalidateDocument(parsedId);
    },
    onError: () => {
      toast.error(t("settings.updateRoleAccessError"));
    },
  });

  const removeRolePermission = useMutation({
    mutationFn: async (roleId: number) => {
      await removeDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdDelete(
        parsedId,
        roleId
      );
    },
    onSuccess: () => {
      toast.success(t("settings.roleAccessRemoved"));
      void invalidateDocument(parsedId);
    },
    onError: () => {
      toast.error(t("settings.removeRoleAccessError"));
    },
  });

  // Roles not yet assigned to the document
  const availableRoles = useMemo(() => {
    const roles = rolesQuery.data ?? [];
    const assignedRoleIds = new Set(
      (document?.role_permissions ?? []).map((rp) => rp.initiative_role_id)
    );
    return roles.filter((role) => !assignedRoleIds.has(role.id));
  }, [rolesQuery.data, document?.role_permissions]);

  const handleTemplateToggle = (value: boolean) => {
    if (!document) {
      return;
    }
    const previous = isTemplate;
    setIsTemplate(value);
    updateTemplate.mutate(value, {
      onError: () => setIsTemplate(previous),
    });
  };

  // Column definitions for the permissions table
  const permissionColumns: ColumnDef<PermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: t("settings.columnName"),
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "email",
        header: t("settings.columnEmail"),
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.columnAccess"),
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <span className="text-muted-foreground">{t("settings.permissionOwner")}</span>;
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) => {
                setAccessMessage(null);
                setAccessError(null);
                updateMemberLevel.mutate({
                  userId: row.original.userId,
                  level: value as DocumentPermissionLevel,
                });
              }}
              disabled={updateMemberLevel.isPending}
            >
              <SelectTrigger className="w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("settings.permissionRead")}</SelectItem>
                <SelectItem value="write">{t("settings.permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.columnActions")}</div>,
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
                {t("settings.remove")}
              </Button>
            </div>
          );
        },
      },
    ],
    [t, updateMemberLevel, removeMember]
  );

  // Column definitions for the role permissions table
  const rolePermissionColumns: ColumnDef<DocumentRolePermission>[] = useMemo(
    () => [
      {
        accessorKey: "role_display_name",
        header: t("settings.columnRoleName"),
        cell: ({ row }) => <span className="font-medium">{row.original.role_display_name}</span>,
      },
      {
        accessorKey: "level",
        header: t("settings.columnAccessLevel"),
        cell: ({ row }) => (
          <Select
            value={row.original.level}
            onValueChange={(value) => {
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
              <SelectItem value="read">{t("settings.canView")}</SelectItem>
              <SelectItem value="write">{t("settings.canEdit")}</SelectItem>
            </SelectContent>
          </Select>
        ),
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("settings.columnActions")}</div>,
        cell: ({ row }) => (
          <div className="text-right">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => removeRolePermission.mutate(row.original.initiative_role_id)}
              disabled={removeRolePermission.isPending}
            >
              {t("settings.remove")}
            </Button>
          </div>
        ),
      },
    ],
    [t, updateRolePermission, removeRolePermission]
  );

  // Initiative members who don't have permissions yet
  const availableMembers = useMemo(
    () =>
      initiativeMembers.filter(
        (member) =>
          member.user &&
          !(document?.permissions ?? []).some((permission) => permission.user_id === member.user.id)
      ),
    [initiativeMembers, document?.permissions]
  );

  if (!Number.isFinite(parsedId)) {
    return <p className="text-destructive">{t("settings.invalidId")}</p>;
  }

  if (documentQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t("settings.loading")}
      </div>
    );
  }

  if (documentQuery.isError || !document) {
    return <p className="text-destructive">{t("settings.notFound")}</p>;
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {document.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to={gp(`/initiatives/${document.initiative.id}`)}>
                    {document.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to={gp(`/documents/${document.id}`)}>{document.title}</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>{t("settings.breadcrumb")}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">{t("settings.title")}</h1>
          <p className="text-muted-foreground text-sm">{t("settings.subtitle")}</p>
        </div>
        <div className="text-muted-foreground flex flex-col items-end gap-2 text-right text-sm">
          <p className="font-medium">{document.title}</p>
          <p>
            {t("detail.updated", {
              date: formatDistanceToNow(new Date(document.updated_at), {
                addSuffix: true,
                locale: dateLocale,
              }),
            })}
          </p>
          {document.initiative ? (
            <span className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs">
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </span>
          ) : null}
        </div>
      </div>

      <Tabs defaultValue="details" className="space-y-4">
        <TabsList className="w-full max-w-xl justify-start">
          <TabsTrigger value="details">{t("settings.tabDetails")}</TabsTrigger>
          {canManageDocument ? (
            <TabsTrigger value="access">{t("settings.tabAccess")}</TabsTrigger>
          ) : null}
          <TabsTrigger value="advanced">{t("settings.tabAdvanced")}</TabsTrigger>
        </TabsList>

        {/* -- Details tab -- */}
        <TabsContent value="details" className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-4">
              <div>
                <CardTitle>{t("settings.templateTitle")}</CardTitle>
                <CardDescription>{t("settings.templateDescription")}</CardDescription>
              </div>
              <Switch
                id="document-template-toggle"
                checked={isTemplate}
                onCheckedChange={handleTemplateToggle}
                disabled={!hasWriteAccess || updateTemplate.isPending}
                aria-label={t("settings.templateToggle")}
              />
            </CardHeader>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("settings.tagsTitle")}</CardTitle>
              <CardDescription>{t("settings.tagsDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              {hasWriteAccess ? (
                <TagPicker
                  selectedTags={documentTags}
                  onChange={(newTags) => {
                    setDocumentTags(newTags);
                    setDocumentTagsMutation.mutate({
                      documentId: parsedId,
                      tagIds: newTags.map((tg) => tg.id),
                    });
                  }}
                />
              ) : (
                <p className="text-muted-foreground text-sm">{t("settings.tagsNoAccess")}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* -- Access tab -- */}
        {canManageDocument ? (
          <TabsContent value="access" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>{t("settings.roleAccessTitle")}</CardTitle>
                <CardDescription>{t("settings.roleAccessDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {(document.role_permissions ?? []).length > 0 ? (
                  <DataTable
                    columns={rolePermissionColumns}
                    data={document.role_permissions ?? []}
                    getRowId={(row) => String(row.initiative_role_id)}
                  />
                ) : (
                  <p className="text-muted-foreground text-sm">{t("settings.noRoleAccess")}</p>
                )}

                {/* Add role form */}
                <div className="space-y-2 pt-2">
                  <Label>{t("settings.addRole")}</Label>
                  {availableRoles.length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      {t("settings.allRolesAssigned")}
                    </p>
                  ) : (
                    <div className="flex flex-wrap items-end gap-3">
                      <Select value={selectedNewRoleId} onValueChange={setSelectedNewRoleId}>
                        <SelectTrigger className="min-w-[200px]">
                          <SelectValue placeholder={t("settings.selectRole")} />
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
                          <SelectItem value="read">{t("settings.canView")}</SelectItem>
                          <SelectItem value="write">{t("settings.canEdit")}</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        type="button"
                        onClick={() => {
                          if (!selectedNewRoleId) {
                            return;
                          }
                          addRolePermission.mutate({
                            roleId: Number(selectedNewRoleId),
                            level: selectedNewRoleLevel,
                          });
                        }}
                        disabled={!selectedNewRoleId || addRolePermission.isPending}
                      >
                        {addRolePermission.isPending ? t("settings.adding") : t("settings.add")}
                      </Button>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("settings.individualAccessTitle")}</CardTitle>
                <CardDescription>{t("settings.individualAccessDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Bulk action bar */}
                {selectedMembers.length > 0 && (
                  <div className="bg-muted flex items-center gap-3 rounded-md p-3">
                    <span className="text-sm font-medium">
                      {t("settings.selectedCount", { count: selectedMembers.length })}
                    </span>
                    <Select
                      onValueChange={(level) => {
                        const userIds = selectedMembers
                          .filter((m) => !m.isOwner)
                          .map((m) => m.userId);
                        if (userIds.length > 0) {
                          bulkUpdateLevel.mutate({
                            userIds,
                            level: level as DocumentPermissionLevel,
                          });
                        }
                      }}
                      disabled={bulkUpdateLevel.isPending || bulkRemoveMembers.isPending}
                    >
                      <SelectTrigger className="w-[150px]">
                        <SelectValue placeholder={t("settings.changeAccess")} />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("settings.permissionRead")}</SelectItem>
                        <SelectItem value="write">{t("settings.permissionWrite")}</SelectItem>
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
                      {bulkRemoveMembers.isPending ? t("settings.removing") : t("settings.remove")}
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
                  filterInputPlaceholder={t("settings.filterByName")}
                  enableRowSelection
                  onRowSelectionChange={setSelectedMembers}
                  onExitSelection={() => setSelectedMembers([])}
                  getRowId={(row) => String(row.userId)}
                />

                {/* Add member form */}
                <div className="space-y-2 pt-2">
                  <Label>{t("settings.grantAccess")}</Label>
                  {availableMembers.length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      {t("settings.allMembersHaveAccess")}
                    </p>
                  ) : (
                    <form
                      className="flex flex-wrap items-end gap-3"
                      onSubmit={(event) => {
                        event.preventDefault();
                        if (!selectedNewUserId) {
                          setAccessError(t("settings.selectMember"));
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
                        placeholder={t("settings.selectMember")}
                        emptyMessage={t("settings.noMembersFound")}
                        className="min-w-[200px]"
                      />
                      <Select
                        value={selectedNewLevel}
                        onValueChange={(value) =>
                          setSelectedNewLevel(value as DocumentPermissionLevel)
                        }
                      >
                        <SelectTrigger className="w-[130px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="read">{t("settings.permissionRead")}</SelectItem>
                          <SelectItem value="write">{t("settings.permissionWrite")}</SelectItem>
                        </SelectContent>
                      </Select>
                      <Button
                        type="submit"
                        disabled={addMember.isPending || addAllMembers.isPending}
                      >
                        {addMember.isPending ? t("settings.adding") : t("settings.add")}
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => addAllMembers.mutate(selectedNewLevel)}
                        disabled={addMember.isPending || addAllMembers.isPending}
                      >
                        {addAllMembers.isPending
                          ? t("settings.adding")
                          : t("settings.addAllCount", { count: availableMembers.length })}
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

        {/* -- Advanced tab -- */}
        <TabsContent value="advanced" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("settings.copiesTitle")}</CardTitle>
              <CardDescription>{t("settings.copiesDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setDuplicateDialogOpen(true);
                  setDuplicateTitle(
                    t("settings.duplicateTitlePlaceholder", { title: document.title })
                  );
                }}
                disabled={!canManageDocument}
              >
                <Copy className="mr-2 h-4 w-4" />
                {t("settings.duplicateDocument")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setCopyDialogOpen(true);
                  setCopyTitle(document.title);
                }}
                disabled={!canManageDocument}
              >
                <ArrowRightLeft className="mr-2 h-4 w-4" />
                {t("settings.copyToInitiative")}
              </Button>
            </CardContent>
          </Card>

          {isOwner ? (
            <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
              <CardHeader>
                <CardTitle>{t("settings.dangerTitle")}</CardTitle>
                <CardDescription>{t("settings.dangerDescription")}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => setDeleteDialogOpen(true)}
                  disabled={!isOwner}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  {t("settings.deleteDocument")}
                </Button>
              </CardContent>
            </Card>
          ) : null}
        </TabsContent>
      </Tabs>

      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("settings.duplicateDialogTitle")}</DialogTitle>
            <DialogDescription>{t("settings.duplicateDialogDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="duplicate-document-title">{t("settings.duplicateTitleLabel")}</Label>
            <Input
              id="duplicate-document-title"
              value={duplicateTitle}
              onChange={(event) => setDuplicateTitle(event.target.value)}
              placeholder={t("settings.duplicateTitlePlaceholder", { title: document.title })}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setDuplicateDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => duplicateDocument.mutate()}
              disabled={duplicateDocument.isPending || !duplicateTitle.trim()}
            >
              {duplicateDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.duplicating")}
                </>
              ) : (
                t("bulk.duplicate")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={copyDialogOpen} onOpenChange={setCopyDialogOpen}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("settings.copyDialogTitle")}</DialogTitle>
            <DialogDescription>{t("settings.copyDialogDescription")}</DialogDescription>
          </DialogHeader>
          {initiativesQuery.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t("settings.loadingInitiatives")}
            </div>
          ) : copyableInitiatives.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("settings.managerAccessRequired")}</p>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="copy-document-initiative">{t("settings.targetInitiative")}</Label>
                <Select
                  value={copyInitiativeId || undefined}
                  onValueChange={(value) => setCopyInitiativeId(value)}
                >
                  <SelectTrigger id="copy-document-initiative">
                    <SelectValue placeholder={t("settings.selectInitiative")} />
                  </SelectTrigger>
                  <SelectContent>
                    {copyableInitiatives.map((initiative) => (
                      <SelectItem key={initiative.id} value={String(initiative.id)}>
                        {initiative.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="copy-document-title">{t("settings.duplicateTitleLabel")}</Label>
                <Input
                  id="copy-document-title"
                  value={copyTitle}
                  onChange={(event) => setCopyTitle(event.target.value)}
                  placeholder={document.title}
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setCopyDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              onClick={() => copyDocument.mutate()}
              disabled={
                copyDocument.isPending ||
                copyableInitiatives.length === 0 ||
                !copyInitiativeId ||
                !copyTitle.trim()
              }
            >
              {copyDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.copying")}
                </>
              ) : (
                t("settings.copyDocument")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("settings.deleteDialogTitle")}</DialogTitle>
            <DialogDescription>{t("settings.deleteDialogDescription")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setDeleteDialogOpen(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => deleteDocument.mutate()}
              disabled={deleteDocument.isPending}
            >
              {deleteDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.deleting")}
                </>
              ) : (
                t("common:delete")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
