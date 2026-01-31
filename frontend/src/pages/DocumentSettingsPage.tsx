import { useEffect, useMemo, useState } from "react";
import { Link, useRouter, useParams } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { formatDistanceToNow } from "date-fns";
import { ArrowRightLeft, Copy, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

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
import { useAuth } from "@/hooks/useAuth";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type { DocumentRead, DocumentPermissionLevel, Initiative } from "@/types/api";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";

const PERMISSION_LABELS: Record<DocumentPermissionLevel, string> = {
  owner: "Owner",
  write: "Can edit",
  read: "Can view",
};

interface PermissionRow {
  userId: number;
  displayName: string;
  level: DocumentPermissionLevel;
  isOwner: boolean;
}

export const DocumentSettingsPage = () => {
  const { documentId } = useParams({ strict: false }) as { documentId: string };
  const parsedId = Number(documentId);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { data: roleLabels } = useRoleLabels();
  const pmLabel = getRoleLabel("project_manager", roleLabels);

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

  const documentQuery = useQuery<DocumentRead>({
    queryKey: ["documents", parsedId],
    queryFn: async () => {
      const response = await apiClient.get<DocumentRead>(`/documents/${parsedId}`);
      return response.data;
    },
    enabled: Number.isFinite(parsedId),
  });

  const document = documentQuery.data;

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
    enabled: Boolean(document) && Boolean(user),
  });

  // Determine if user can manage the document (owner, initiative PM, or guild admin)
  const canManageDocument = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    if (user.role === "admin") {
      return true;
    }
    // Check if user is initiative PM
    const initiativeMembers = document.initiative?.members ?? [];
    const isManager = initiativeMembers.some(
      (member) => member.user.id === user.id && member.role === "project_manager"
    );
    if (isManager) {
      return true;
    }
    // Check if user is document owner
    const ownerPermission = (document.permissions ?? []).find(
      (p) => p.user_id === user.id && p.level === "owner"
    );
    return Boolean(ownerPermission);
  }, [document, user]);

  // Check if user has write access (for editing content, not managing permissions)
  const hasWriteAccess = useMemo(() => {
    if (!document || !user) {
      return false;
    }
    if (user.role === "admin") {
      return true;
    }
    const initiativeMembers = document.initiative?.members ?? [];
    const isManager = initiativeMembers.some(
      (member) => member.user.id === user.id && member.role === "project_manager"
    );
    if (isManager) {
      return true;
    }
    const permission = (document.permissions ?? []).find((p) => p.user_id === user.id);
    return permission?.level === "owner" || permission?.level === "write";
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
        member?.user?.full_name?.trim() || member?.user?.email || `User ${permission.user_id}`;
      return {
        userId: permission.user_id,
        displayName,
        level: permission.level,
        isOwner: permission.level === "owner",
      };
    });
  }, [document?.permissions, initiativeMembers]);

  useEffect(() => {
    if (!document) {
      return;
    }
    setIsTemplate(document.is_template);
    setDuplicateTitle(`${document.title} (Copy)`);
    setCopyTitle(document.title);
    setAccessMessage(null);
    setAccessError(null);
  }, [document]);

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
      await apiClient.post(`/documents/${parsedId}/members`, {
        user_id: userId,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access granted");
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["documents", parsedId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to grant access");
    },
  });

  const updateMemberLevel = useMutation({
    mutationFn: async ({ userId, level }: { userId: number; level: DocumentPermissionLevel }) => {
      await apiClient.patch(`/documents/${parsedId}/members/${userId}`, {
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access updated");
      setAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["documents", parsedId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to update access");
    },
  });

  const removeMember = useMutation({
    mutationFn: async (userId: number) => {
      await apiClient.delete(`/documents/${parsedId}/members/${userId}`);
    },
    onSuccess: () => {
      setAccessMessage("Access removed");
      setAccessError(null);
      void queryClient.invalidateQueries({ queryKey: ["documents", parsedId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to remove access");
    },
  });

  const addAllMembers = useMutation({
    mutationFn: async (level: DocumentPermissionLevel) => {
      const userIds = availableMembers.map((member) => member.user.id);
      await apiClient.post(`/documents/${parsedId}/members/bulk`, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access granted to all members");
      setAccessError(null);
      setSelectedNewUserId("");
      setSelectedNewLevel("read");
      void queryClient.invalidateQueries({ queryKey: ["documents", parsedId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to grant access to all members");
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
      await apiClient.post(`/documents/${parsedId}/members/bulk`, {
        user_ids: userIds,
        level,
      });
    },
    onSuccess: () => {
      setAccessMessage("Access updated for selected members");
      setAccessError(null);
      setSelectedMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["documents", parsedId] });
    },
    onError: () => {
      setAccessMessage(null);
      setAccessError("Unable to update access for selected members");
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
      const response = await apiClient.post<DocumentRead>(`/documents/${document.id}/duplicate`, {
        title: trimmedTitle,
      });
      return response.data;
    },
    onSuccess: (duplicated) => {
      toast.success("Document duplicated");
      setDuplicateDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      router.navigate({
        to: "/documents/$documentId",
        params: { documentId: String(duplicated.id) },
      });
    },
    onError: (error) => {
      const message =
        error instanceof Error ? error.message : "Unable to duplicate document right now.";
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
      const payload = {
        target_initiative_id: Number(copyInitiativeId),
        title: trimmedTitle,
      };
      const response = await apiClient.post<DocumentRead>(
        `/documents/${document.id}/copy`,
        payload
      );
      return response.data;
    },
    onSuccess: (copied) => {
      toast.success("Document copied");
      setCopyDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      router.navigate({ to: "/documents/$documentId", params: { documentId: String(copied.id) } });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : "Unable to copy document right now.";
      toast.error(message);
    },
  });

  const deleteDocument = useMutation({
    mutationFn: async () => {
      await apiClient.delete(`/documents/${parsedId}`);
    },
    onSuccess: () => {
      toast.success("Document deleted");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      setDeleteDialogOpen(false);
      router.navigate({ to: "/documents" });
    },
    onError: () => {
      toast.error("Unable to delete document right now.");
    },
  });

  const updateTemplate = useMutation({
    mutationFn: async (nextValue: boolean) => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      const response = await apiClient.patch<DocumentRead>(`/documents/${document.id}`, {
        is_template: nextValue,
      });
      return response.data;
    },
    onSuccess: (updated) => {
      setIsTemplate(updated.is_template);
      queryClient.setQueryData(["documents", parsedId], updated);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: () => {
      toast.error("Unable to update template status.");
    },
  });

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
        header: "Name",
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "level",
        header: "Access",
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <span className="text-muted-foreground">Owner</span>;
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
                <SelectItem value="read">{PERMISSION_LABELS.read}</SelectItem>
                <SelectItem value="write">{PERMISSION_LABELS.write}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">Actions</div>,
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
                Remove
              </Button>
            </div>
          );
        },
      },
    ],
    [updateMemberLevel, removeMember]
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
    return <p className="text-destructive">Invalid document id.</p>;
  }

  if (documentQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading document…
      </div>
    );
  }

  if (documentQuery.isError || !document) {
    return <p className="text-destructive">Document not found.</p>;
  }

  return (
    <div className="space-y-6">
      <Breadcrumb>
        <BreadcrumbList>
          {document.initiative && (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link
                    to="/initiatives/$initiativeId"
                    params={{ initiativeId: String(document.initiative.id) }}
                  >
                    {document.initiative.name}
                  </Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
            </>
          )}
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/documents/$documentId" params={{ documentId: String(document.id) }}>
                {document.title}
              </Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Settings</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">Document settings</h1>
          <p className="text-muted-foreground text-sm">
            Manage access, template status, duplication, and deletion.
          </p>
        </div>
        <div className="text-muted-foreground flex flex-col items-end gap-2 text-right text-sm">
          <p className="font-medium">{document.title}</p>
          <p>Updated {formatDistanceToNow(new Date(document.updated_at), { addSuffix: true })}</p>
          {document.initiative ? (
            <span className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs">
              <InitiativeColorDot color={document.initiative.color} />
              {document.initiative.name}
            </span>
          ) : null}
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>Template</CardTitle>
            <CardDescription>
              Template documents are intended to be duplicated instead of edited directly.
            </CardDescription>
          </div>
          <Switch
            id="document-template-toggle"
            checked={isTemplate}
            onCheckedChange={handleTemplateToggle}
            disabled={!hasWriteAccess || updateTemplate.isPending}
            aria-label="Toggle template status"
          />
        </CardHeader>
      </Card>

      {canManageDocument ? (
        <Card>
          <CardHeader>
            <CardTitle>Document access</CardTitle>
            <CardDescription>
              Control who can view and edit this document. {pmLabel}s have full access to all
              documents in their initiatives.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Bulk action bar */}
            {selectedMembers.length > 0 && (
              <div className="bg-muted flex items-center gap-3 rounded-md p-3">
                <span className="text-sm font-medium">{selectedMembers.length} selected</span>
                <Select
                  onValueChange={(level) => {
                    const userIds = selectedMembers.filter((m) => !m.isOwner).map((m) => m.userId);
                    if (userIds.length > 0) {
                      bulkUpdateLevel.mutate({
                        userIds,
                        level: level as DocumentPermissionLevel,
                      });
                    }
                  }}
                  disabled={bulkUpdateLevel.isPending}
                >
                  <SelectTrigger className="w-[150px]">
                    <SelectValue placeholder="Change access..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{PERMISSION_LABELS.read}</SelectItem>
                    <SelectItem value="write">{PERMISSION_LABELS.write}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Access table */}
            <DataTable
              columns={permissionColumns}
              data={permissionRows}
              enablePagination
              enableFilterInput
              filterInputColumnKey="displayName"
              filterInputPlaceholder="Filter by name"
              enableRowSelection
              onRowSelectionChange={setSelectedMembers}
              onExitSelection={() => setSelectedMembers([])}
              getRowId={(row) => String(row.userId)}
            />

            {/* Add member form */}
            <div className="space-y-2 pt-2">
              <Label>Grant access</Label>
              {availableMembers.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  All initiative members already have access to this document.
                </p>
              ) : (
                <form
                  className="flex flex-wrap items-end gap-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!selectedNewUserId) {
                      setAccessError("Select a member");
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
                    placeholder="Select member"
                    emptyMessage="No members found"
                    className="min-w-[200px]"
                  />
                  <Select
                    value={selectedNewLevel}
                    onValueChange={(value) => setSelectedNewLevel(value as DocumentPermissionLevel)}
                  >
                    <SelectTrigger className="w-[130px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="read">{PERMISSION_LABELS.read}</SelectItem>
                      <SelectItem value="write">{PERMISSION_LABELS.write}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button type="submit" disabled={addMember.isPending || addAllMembers.isPending}>
                    {addMember.isPending ? "Adding..." : "Add"}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => addAllMembers.mutate(selectedNewLevel)}
                    disabled={addMember.isPending || addAllMembers.isPending}
                  >
                    {addAllMembers.isPending
                      ? "Adding all..."
                      : `Add all (${availableMembers.length})`}
                  </Button>
                </form>
              )}
              {accessMessage ? <p className="text-primary text-sm">{accessMessage}</p> : null}
              {accessError ? <p className="text-destructive text-sm">{accessError}</p> : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Copies</CardTitle>
          <CardDescription>
            Duplicate this document within the same initiative or copy it into another initiative.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setDuplicateDialogOpen(true);
              setDuplicateTitle(`${document.title} (Copy)`);
            }}
            disabled={!canManageDocument}
          >
            <Copy className="mr-2 h-4 w-4" />
            Duplicate document
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
            Copy to initiative
          </Button>
        </CardContent>
      </Card>

      <Card className="border-destructive/40 bg-destructive/5 shadow-sm">
        <CardHeader>
          <CardTitle>Danger zone</CardTitle>
          <CardDescription>Deleting a document cannot be undone.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            type="button"
            variant="destructive"
            onClick={() => setDeleteDialogOpen(true)}
            disabled={!canManageDocument}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete document
          </Button>
        </CardContent>
      </Card>

      <Dialog open={duplicateDialogOpen} onOpenChange={setDuplicateDialogOpen}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Duplicate document</DialogTitle>
            <DialogDescription>
              Create a copy inside {document.initiative?.name ?? "this initiative"}.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="duplicate-document-title">Title</Label>
            <Input
              id="duplicate-document-title"
              value={duplicateTitle}
              onChange={(event) => setDuplicateTitle(event.target.value)}
              placeholder={`${document.title} (Copy)`}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setDuplicateDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => duplicateDocument.mutate()}
              disabled={duplicateDocument.isPending || !duplicateTitle.trim()}
            >
              {duplicateDocument.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Duplicating…
                </>
              ) : (
                "Duplicate"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={copyDialogOpen} onOpenChange={setCopyDialogOpen}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Copy to another initiative</DialogTitle>
            <DialogDescription>
              Select a target initiative and optional title for the copy.
            </DialogDescription>
          </DialogHeader>
          {initiativesQuery.isLoading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading initiatives…
            </div>
          ) : copyableInitiatives.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              You need manager access in another initiative to copy this document.
            </p>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="copy-document-initiative">Target initiative</Label>
                <Select
                  value={copyInitiativeId || undefined}
                  onValueChange={(value) => setCopyInitiativeId(value)}
                >
                  <SelectTrigger id="copy-document-initiative">
                    <SelectValue placeholder="Select initiative" />
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
                <Label htmlFor="copy-document-title">Title</Label>
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
              Cancel
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
                  Copying…
                </>
              ) : (
                "Copy document"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="bg-card max-h-screen overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Delete this document?</DialogTitle>
            <DialogDescription>
              This removes the document for everyone and detaches it from any projects.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
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
                  Deleting…
                </>
              ) : (
                "Delete"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
