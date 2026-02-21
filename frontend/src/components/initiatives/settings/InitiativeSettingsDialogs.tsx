import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  InitiativeMemberRead,
  InitiativeRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import { useCreateRole, useUpdateRole, useDeleteRole } from "@/hooks/useInitiativeRoles";
import { useRemoveInitiativeMember } from "@/hooks/useInitiatives";
import { toast } from "sonner";

interface InitiativeSettingsDialogsProps {
  initiativeId: number;
  initiativeName: string;

  // Delete initiative dialog
  showDeleteConfirm: boolean;
  setShowDeleteConfirm: (open: boolean) => void;
  isDeletingInitiative: boolean;
  onConfirmDeleteInitiative: () => void;

  // Create role dialog
  showNewRoleDialog: boolean;
  setShowNewRoleDialog: (open: boolean) => void;

  // Delete role dialog
  roleToDelete: InitiativeRoleRead | null;
  setRoleToDelete: (role: InitiativeRoleRead | null) => void;

  // Rename role dialog
  roleToRename: InitiativeRoleRead | null;
  setRoleToRename: (role: InitiativeRoleRead | null) => void;

  // Remove member dialog
  memberToRemove: InitiativeMemberRead | null;
  setMemberToRemove: (member: InitiativeMemberRead | null) => void;
}

export const InitiativeSettingsDialogs = ({
  initiativeId,
  initiativeName,
  showDeleteConfirm,
  setShowDeleteConfirm,
  isDeletingInitiative,
  onConfirmDeleteInitiative,
  showNewRoleDialog,
  setShowNewRoleDialog,
  roleToDelete,
  setRoleToDelete,
  roleToRename,
  setRoleToRename,
  memberToRemove,
  setMemberToRemove,
}: InitiativeSettingsDialogsProps) => {
  const { t } = useTranslation(["initiatives", "common"]);

  // Delete initiative confirmation text
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const canConfirmDelete = deleteConfirmText === initiativeName;

  // Reset delete confirm text when dialog opens
  useEffect(() => {
    if (showDeleteConfirm) {
      setDeleteConfirmText("");
    }
  }, [showDeleteConfirm]);

  // New role dialog state
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleDisplayName, setNewRoleDisplayName] = useState("");
  const roleNameTouchedRef = useRef(false);

  // Rename role dialog state
  const [renameDisplayName, setRenameDisplayName] = useState("");

  // Sync renameDisplayName when roleToRename changes
  useEffect(() => {
    if (roleToRename) {
      setRenameDisplayName(roleToRename.display_name);
    }
  }, [roleToRename]);

  // Mutations
  const createRoleMutation = useCreateRole(initiativeId);
  const updateRoleMutation = useUpdateRole(initiativeId);
  const deleteRoleMutation = useDeleteRole(initiativeId);

  const removeMember = useRemoveInitiativeMember({
    onSuccess: () => {
      toast.success(t("settings.memberRemoved"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("settings.removeMemberError");
      toast.error(message);
    },
  });

  const handleCreateRole = () => {
    const name = newRoleName.trim().toLowerCase().replace(/\s+/g, "_");
    const displayName = newRoleDisplayName.trim();
    if (!name || !displayName) {
      toast.error(t("settings.roleNameRequired"));
      return;
    }
    createRoleMutation.mutate(
      { name, display_name: displayName },
      {
        onSuccess: () => {
          setShowNewRoleDialog(false);
          setNewRoleName("");
          setNewRoleDisplayName("");
          roleNameTouchedRef.current = false;
        },
      }
    );
  };

  const confirmDeleteRole = () => {
    if (roleToDelete) {
      deleteRoleMutation.mutate(roleToDelete.id, {
        onSuccess: () => setRoleToDelete(null),
      });
    }
  };

  const confirmRenameRole = () => {
    if (roleToRename && renameDisplayName.trim()) {
      updateRoleMutation.mutate(
        { roleId: roleToRename.id, data: { display_name: renameDisplayName.trim() } },
        { onSuccess: () => setRoleToRename(null) }
      );
    }
  };

  return (
    <>
      {/* Delete Initiative Dialog */}
      <AlertDialog
        open={showDeleteConfirm}
        onOpenChange={(open) => {
          setShowDeleteConfirm(open);
          if (!open) setDeleteConfirmText("");
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="settings.deleteConfirmDescription"
                ns="initiatives"
                values={{ name: initiativeName }}
                components={{ bold: <strong /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="delete-confirm-input">
              <Trans
                i18nKey="settings.deleteConfirmLabel"
                ns="initiatives"
                values={{ name: initiativeName }}
                components={{ bold: <strong /> }}
              />
            </Label>
            <Input
              id="delete-confirm-input"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder={initiativeName}
              autoComplete="off"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeletingInitiative}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={onConfirmDeleteInitiative}
              disabled={!canConfirmDelete || isDeletingInitiative}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {isDeletingInitiative ? t("settings.deletingInitiative") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* New Role Dialog */}
      <Dialog
        open={showNewRoleDialog}
        onOpenChange={(open) => {
          setShowNewRoleDialog(open);
          if (!open) roleNameTouchedRef.current = false;
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.createRoleTitle")}</DialogTitle>
            <DialogDescription>{t("settings.createRoleDescription")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="new-role-display-name">{t("settings.roleDisplayNameLabel")}</Label>
              <Input
                id="new-role-display-name"
                value={newRoleDisplayName}
                onChange={(e) => {
                  const display = e.target.value;
                  setNewRoleDisplayName(display);
                  if (!roleNameTouchedRef.current) {
                    setNewRoleName(
                      display
                        .trim()
                        .toLowerCase()
                        .replace(/\s+/g, "_")
                        .replace(/[^a-z0-9_]/g, "")
                    );
                  }
                }}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-role-name">{t("settings.roleInternalNameLabel")}</Label>
              <Input
                id="new-role-name"
                value={newRoleName}
                onChange={(e) => {
                  const snakeCase = e.target.value
                    .toLowerCase()
                    .replace(/\s+/g, "_")
                    .replace(/[^a-z0-9_]/g, "");
                  setNewRoleName(snakeCase);
                  if (!snakeCase && !newRoleDisplayName) {
                    roleNameTouchedRef.current = false;
                  } else {
                    roleNameTouchedRef.current = true;
                  }
                }}
                placeholder={t("settings.roleInternalNamePlaceholder")}
              />
              <p className="text-muted-foreground text-xs">{t("settings.roleInternalNameHint")}</p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewRoleDialog(false)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={handleCreateRole}
              disabled={
                createRoleMutation.isPending || !newRoleName.trim() || !newRoleDisplayName.trim()
              }
            >
              {createRoleMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.creatingRole")}
                </>
              ) : (
                t("settings.createRole")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Role Confirmation Dialog */}
      <AlertDialog open={!!roleToDelete} onOpenChange={(open) => !open && setRoleToDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteRoleTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.deleteRoleDescription", { roleName: roleToDelete?.display_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteRoleMutation.isPending}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDeleteRole}
              disabled={deleteRoleMutation.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {deleteRoleMutation.isPending ? t("settings.deletingRole") : t("common:delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Rename Role Dialog */}
      <Dialog open={!!roleToRename} onOpenChange={(open) => !open && setRoleToRename(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("settings.renameRoleTitle")}</DialogTitle>
            <DialogDescription>
              {t("settings.renameRoleDescription", { roleName: roleToRename?.display_name })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="rename-role-display-name">{t("settings.roleDisplayNameLabel")}</Label>
              <Input
                id="rename-role-display-name"
                value={renameDisplayName}
                onChange={(e) => setRenameDisplayName(e.target.value)}
                placeholder={t("settings.roleDisplayNamePlaceholder")}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRoleToRename(null)}>
              {t("common:cancel")}
            </Button>
            <Button
              onClick={confirmRenameRole}
              disabled={updateRoleMutation.isPending || !renameDisplayName.trim()}
            >
              {updateRoleMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("settings.savingRole")}
                </>
              ) : (
                t("common:save")
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Remove Member Confirmation Dialog */}
      <AlertDialog
        open={!!memberToRemove}
        onOpenChange={(open) => !open && setMemberToRemove(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.removeMemberTitle")}</AlertDialogTitle>
            <AlertDialogDescription className="space-y-2">
              <span className="block">
                <Trans
                  i18nKey="settings.removeMemberDescription"
                  ns="initiatives"
                  values={{
                    name: memberToRemove?.user.full_name || memberToRemove?.user.email,
                  }}
                  components={{ bold: <strong /> }}
                />
              </span>
              <span className="text-destructive block">{t("settings.removeMemberWarning")}</span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removeMember.isPending}>
              {t("common:cancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (memberToRemove) {
                  removeMember.mutate(
                    { initiativeId, userId: memberToRemove.user.id },
                    { onSuccess: () => setMemberToRemove(null) }
                  );
                }
              }}
              disabled={removeMember.isPending}
              className="bg-destructive hover:bg-destructive/90 text-white"
            >
              {removeMember.isPending ? t("settings.removing") : t("settings.removeMember")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
};
