import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ArrowRightLeft, Copy, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type { DocumentRead, Initiative } from "@/types/api";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";

export const DocumentSettingsPage = () => {
  const { documentId } = useParams();
  const parsedId = Number(documentId);
  const navigate = useNavigate();
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
  const [writeMemberIds, setWriteMemberIds] = useState<number[]>([]);

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

  const canManageDocument = useMemo(() => {
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
    return (document.write_member_ids ?? []).includes(user.id);
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

  useEffect(() => {
    if (!document) {
      return;
    }
    setIsTemplate(document.is_template);
    setWriteMemberIds(document.write_member_ids ?? []);
    setDuplicateTitle(`${document.title} (Copy)`);
    setCopyTitle(document.title);
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
      navigate(`/documents/${duplicated.id}`);
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
      navigate(`/documents/${copied.id}`);
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
      navigate("/documents");
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

  const updatePermissions = useMutation({
    mutationFn: async (nextWriteMembers: number[]) => {
      if (!document) {
        throw new Error("Document is not loaded yet.");
      }
      const response = await apiClient.put<DocumentRead>(`/documents/${document.id}/permissions`, {
        write_member_ids: nextWriteMembers,
      });
      return response.data;
    },
    onSuccess: (updated) => {
      setWriteMemberIds(updated.write_member_ids ?? []);
      queryClient.setQueryData(["documents", parsedId], updated);
      toast.success("Permissions updated");
    },
    onError: () => {
      toast.error("Unable to update permissions right now.");
      setWriteMemberIds(document?.write_member_ids ?? []);
    },
  });

  const handlePermissionToggle = (memberId: number, enable: boolean) => {
    if (!document || updatePermissions.isPending) {
      return;
    }
    const next = new Set(writeMemberIds);
    if (enable) {
      next.add(memberId);
    } else {
      next.delete(memberId);
    }
    const nextArray = Array.from(next).sort((a, b) => a - b);
    setWriteMemberIds(nextArray);
    updatePermissions.mutate(nextArray);
  };

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

  const attachedMembers = document.initiative?.members ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <Button asChild variant="link" className="px-0">
            <Link to={`/documents/${document.id}`}>← Back to document</Link>
          </Button>
          <h1 className="text-2xl font-semibold">Document settings</h1>
          <p className="text-muted-foreground text-sm">
            Manage template status, permissions, duplication, and deletion.
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
            disabled={!canManageDocument || updateTemplate.isPending}
            aria-label="Toggle template status"
          />
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Editor permissions</CardTitle>
          <CardDescription>
            {pmLabel}s can always edit. Grant additional editors for this document.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {attachedMembers.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Add members to the initiative to manage document access.
            </p>
          ) : (
            <div className="space-y-3">
              {attachedMembers.map((member) => {
                const memberUser = member.user;
                const memberId = memberUser?.id;
                const isManager = member.role === "project_manager";
                const canEdit = isManager || (memberId ? writeMemberIds.includes(memberId) : false);
                const displayName = memberUser?.full_name || memberUser?.email || "Member";
                const canToggle = Boolean(canManageDocument && !isManager && memberId);
                return (
                  <div
                    key={`document-permission-${memberId ?? displayName}`}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2"
                  >
                    <div>
                      <p className="text-sm font-medium">{displayName}</p>
                      <p className="text-muted-foreground text-xs">
                        {isManager ? pmLabel : "Member"}
                        {memberId === user?.id ? " · You" : null}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {isManager ? (
                        <Badge variant="outline">Always editor</Badge>
                      ) : (
                        <>
                          <span className="text-muted-foreground text-xs">Can edit</span>
                          <Switch
                            checked={canEdit}
                            onCheckedChange={(value) =>
                              memberId ? handlePermissionToggle(memberId, value) : undefined
                            }
                            disabled={!canToggle || updatePermissions.isPending}
                            aria-label={`Toggle edit access for ${displayName}`}
                          />
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

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
        <DialogContent>
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
        <DialogContent>
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
        <DialogContent>
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
