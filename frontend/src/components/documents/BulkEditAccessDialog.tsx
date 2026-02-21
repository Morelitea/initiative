import { useCallback, useMemo, useState } from "react";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { useQueries } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost,
  addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost,
  removeDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkDeletePost,
  removeDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdDelete,
} from "@/api/generated/documents/documents";
import {
  getListInitiativeRolesApiV1InitiativesInitiativeIdRolesGetQueryKey,
  listInitiativeRolesApiV1InitiativesInitiativeIdRolesGet,
} from "@/api/generated/initiatives/initiatives";
import { invalidateAllDocuments } from "@/api/query-keys";
import { useInitiatives } from "@/hooks/useInitiatives";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import type {
  DocumentPermissionLevel,
  DocumentSummary,
  InitiativeMemberRead,
  InitiativeRoleRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { DialogWithSuccessProps } from "@/types/dialog";

interface BulkEditAccessDialogProps extends DialogWithSuccessProps {
  documents: DocumentSummary[];
}

interface SelectableUser {
  id: number;
  name: string;
  email: string;
}

interface SelectableRole {
  id: number;
  name: string;
  displayName: string;
  initiativeId: number;
  initiativeName: string;
}

export function BulkEditAccessDialog({
  open,
  onOpenChange,
  documents,
  onSuccess,
}: BulkEditAccessDialogProps) {
  const { t } = useTranslation(["documents", "common"]);
  const { user: currentUser } = useAuth();
  const [tab, setTab] = useState<"roles" | "users">("roles");
  const [isPending, setIsPending] = useState(false);

  // Individual user state
  const [userMode, setUserMode] = useState<"grant" | "revoke">("grant");
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [level, setLevel] = useState<DocumentPermissionLevel>("read");
  const [userPickerOpen, setUserPickerOpen] = useState(false);
  const [userSearch, setUserSearch] = useState("");

  // Role state
  const [roleMode, setRoleMode] = useState<"grant" | "revoke">("grant");
  const [selectedRoleIds, setSelectedRoleIds] = useState<Set<number>>(new Set());
  const [roleLevel, setRoleLevel] = useState<"read" | "write">("read");
  const [rolePickerOpen, setRolePickerOpen] = useState(false);
  const [roleSearch, setRoleSearch] = useState("");

  // Gather unique initiative IDs from selected documents
  const initiativeIds = useMemo(() => {
    const ids = new Set<number>();
    for (const doc of documents) {
      if (doc.initiative_id) ids.add(doc.initiative_id);
    }
    return [...ids];
  }, [documents]);

  // Fetch initiative data to get member lists
  const { data: initiatives = [] } = useInitiatives({ enabled: open });

  // Fetch roles for each relevant initiative (reuses same query key as useInitiativeRoles)
  const roleQueries = useQueries({
    queries: initiativeIds.map((id) => ({
      queryKey: getListInitiativeRolesApiV1InitiativesInitiativeIdRolesGetQueryKey(id),
      queryFn: () =>
        listInitiativeRolesApiV1InitiativesInitiativeIdRolesGet(id) as unknown as Promise<
          InitiativeRoleRead[]
        >,
      enabled: open,
    })),
  });

  // Build selectable roles from all relevant initiatives
  const availableRoles = useMemo(() => {
    const roles: SelectableRole[] = [];
    for (let i = 0; i < roleQueries.length; i++) {
      const query = roleQueries[i];
      const initiativeId = initiativeIds[i];
      if (!query.data) continue;
      const initiative = initiatives.find((init) => init.id === initiativeId);
      for (const role of query.data) {
        roles.push({
          id: role.id,
          name: role.name,
          displayName: role.display_name,
          initiativeId,
          initiativeName: initiative?.name ?? `Initiative ${initiativeId}`,
        });
      }
    }
    return roles.sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [roleQueries, initiativeIds, initiatives]);

  // Roles that are currently assigned on at least one selected document (for revoke)
  const revocableRoles = useMemo(() => {
    const roleMap = new Map<number, SelectableRole>();
    for (const doc of documents) {
      for (const rp of doc.role_permissions ?? []) {
        if (!roleMap.has(rp.initiative_role_id)) {
          roleMap.set(rp.initiative_role_id, {
            id: rp.initiative_role_id,
            name: rp.role_name,
            displayName: rp.role_display_name,
            initiativeId: doc.initiative_id,
            initiativeName: doc.initiative?.name ?? `Initiative ${doc.initiative_id}`,
          });
        }
      }
    }
    return Array.from(roleMap.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [documents]);

  const displayRoles = roleMode === "grant" ? availableRoles : revocableRoles;

  const filteredRoles = useMemo(() => {
    if (!roleSearch.trim()) return displayRoles;
    const searchLower = roleSearch.toLowerCase();
    return displayRoles.filter(
      (r) =>
        r.displayName.toLowerCase().includes(searchLower) ||
        r.initiativeName.toLowerCase().includes(searchLower)
    );
  }, [displayRoles, roleSearch]);

  // Build list of users from initiatives the selected documents belong to
  const availableUsers = useMemo(() => {
    const userMap = new Map<number, SelectableUser>();
    const relevantInitiatives = initiatives.filter((i) => initiativeIds.includes(i.id));
    for (const initiative of relevantInitiatives) {
      for (const member of initiative.members) {
        if (member.user.id !== currentUser?.id && !userMap.has(member.user.id)) {
          userMap.set(member.user.id, {
            id: member.user.id,
            name: member.user.full_name || member.user.email,
            email: member.user.email,
          });
        }
      }
    }
    return Array.from(userMap.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [initiatives, initiativeIds, currentUser]);

  // Users who have non-owner access on at least one selected document (for revoke)
  const revocableUsers = useMemo(() => {
    const userMap = new Map<number, SelectableUser>();
    for (const doc of documents) {
      for (const perm of doc.permissions ?? []) {
        if (
          perm.level !== "owner" &&
          perm.user_id !== currentUser?.id &&
          !userMap.has(perm.user_id)
        ) {
          // Try to find user info from initiative members
          const initiative = doc.initiative;
          const member = initiative?.members?.find(
            (m: InitiativeMemberRead) => m.user.id === perm.user_id
          );
          userMap.set(perm.user_id, {
            id: perm.user_id,
            name: member?.user?.full_name || member?.user?.email || `User ${perm.user_id}`,
            email: member?.user?.email || "",
          });
        }
      }
    }
    return Array.from(userMap.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [documents, currentUser]);

  const displayUsers = userMode === "grant" ? availableUsers : revocableUsers;

  const filteredUsers = useMemo(() => {
    if (!userSearch.trim()) return displayUsers;
    const searchLower = userSearch.toLowerCase();
    return displayUsers.filter(
      (u) =>
        u.name.toLowerCase().includes(searchLower) || u.email.toLowerCase().includes(searchLower)
    );
  }, [displayUsers, userSearch]);

  const toggleUser = useCallback((userId: number) => {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) {
        next.delete(userId);
      } else {
        next.add(userId);
      }
      return next;
    });
  }, []);

  const toggleRole = useCallback((roleId: number) => {
    setSelectedRoleIds((prev) => {
      const next = new Set(prev);
      if (next.has(roleId)) {
        next.delete(roleId);
      } else {
        next.add(roleId);
      }
      return next;
    });
  }, []);

  const resetState = useCallback(() => {
    setTab("roles");
    setUserMode("grant");
    setSelectedUserIds(new Set());
    setLevel("read");
    setUserSearch("");
    setUserPickerOpen(false);
    setRoleMode("grant");
    setSelectedRoleIds(new Set());
    setRoleLevel("read");
    setRoleSearch("");
    setRolePickerOpen(false);
  }, []);

  const handleOpenChange = useCallback(
    (value: boolean) => {
      if (!value) {
        resetState();
      }
      onOpenChange(value);
    },
    [onOpenChange, resetState]
  );

  const handleApply = useCallback(async () => {
    if (selectedUserIds.size === 0) return;

    setIsPending(true);
    try {
      const userIds = [...selectedUserIds];

      if (userMode === "grant") {
        await Promise.all(
          documents.map((doc) =>
            addDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkPost(doc.id, {
              user_ids: userIds,
              level,
            })
          )
        );
        toast.success(t("bulkAccess.userAccessGranted", { count: documents.length }));
      } else {
        await Promise.all(
          documents.map((doc) =>
            removeDocumentMembersBulkApiV1DocumentsDocumentIdMembersBulkDeletePost(doc.id, {
              user_ids: userIds,
            })
          )
        );
        toast.success(t("bulkAccess.userAccessRevoked", { count: documents.length }));
      }

      void invalidateAllDocuments();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("bulkAccess.updateError");
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  }, [selectedUserIds, userMode, documents, level, resetState, onOpenChange, onSuccess, t]);

  const handleApplyRoles = useCallback(async () => {
    if (selectedRoleIds.size === 0) return;

    setIsPending(true);
    try {
      const roleIds = [...selectedRoleIds];

      const affectedDocIds = new Set<number>();

      if (roleMode === "grant") {
        // For each document, grant each selected role (only if the role belongs to that doc's initiative)
        const promises: Promise<unknown>[] = [];
        for (const doc of documents) {
          const docRoles = availableRoles.filter(
            (r) => r.initiativeId === doc.initiative_id && roleIds.includes(r.id)
          );
          for (const role of docRoles) {
            // Skip if already assigned
            const alreadyAssigned = (doc.role_permissions ?? []).some(
              (rp) => rp.initiative_role_id === role.id
            );
            if (!alreadyAssigned) {
              affectedDocIds.add(doc.id);
              promises.push(
                addDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsPost(doc.id, {
                  initiative_role_id: role.id,
                  level: roleLevel,
                })
              );
            }
          }
        }
        await Promise.all(promises);
        const affected = affectedDocIds.size;
        if (affected === 0) {
          toast.info(t("bulkAccess.rolesAlreadyAssigned"));
        } else {
          toast.success(t("bulkAccess.roleAccessGranted", { count: affected }));
        }
      } else {
        // For each document, revoke each selected role
        const promises: Promise<unknown>[] = [];
        for (const doc of documents) {
          for (const roleId of roleIds) {
            const isAssigned = (doc.role_permissions ?? []).some(
              (rp) => rp.initiative_role_id === roleId
            );
            if (isAssigned) {
              affectedDocIds.add(doc.id);
              promises.push(
                removeDocumentRolePermissionApiV1DocumentsDocumentIdRolePermissionsRoleIdDelete(
                  doc.id,
                  roleId
                )
              );
            }
          }
        }
        await Promise.all(promises);
        const affected = affectedDocIds.size;
        if (affected === 0) {
          toast.info(t("bulkAccess.rolesAlreadyAssigned"));
        } else {
          toast.success(t("bulkAccess.roleAccessRevoked", { count: affected }));
        }
      }

      void invalidateAllDocuments();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      const message = error instanceof Error ? error.message : t("bulkAccess.roleUpdateError");
      toast.error(message);
    } finally {
      setIsPending(false);
    }
  }, [
    selectedRoleIds,
    roleMode,
    roleLevel,
    documents,
    availableRoles,
    resetState,
    onOpenChange,
    onSuccess,
    t,
  ]);

  const selectedUserCount = selectedUserIds.size;
  const selectedRoleCount = selectedRoleIds.size;
  const canApplyUsers = selectedUserCount > 0;
  const canApplyRoles = selectedRoleCount > 0;

  const activeMode = tab === "roles" ? roleMode : userMode;
  const docCount = documents.length;
  const dialogDescription = useMemo(() => {
    if (tab === "roles") {
      return activeMode === "grant"
        ? t("bulkAccess.descriptionGrant", { count: docCount })
        : t("bulkAccess.descriptionRevoke", { count: docCount });
    }
    return activeMode === "grant"
      ? t("bulkAccess.descriptionGrantUser", { count: docCount })
      : t("bulkAccess.descriptionRevokeUser", { count: docCount });
  }, [tab, activeMode, docCount, t]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("bulkAccess.title")}</DialogTitle>
          <DialogDescription>{dialogDescription}</DialogDescription>
        </DialogHeader>

        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as "roles" | "users");
            setSelectedUserIds(new Set());
            setUserSearch("");
            setUserPickerOpen(false);
            setSelectedRoleIds(new Set());
            setRoleSearch("");
            setRolePickerOpen(false);
          }}
        >
          <TabsList className="w-full">
            <TabsTrigger value="roles" className="flex-1">
              {t("bulkAccess.tabRoles")}
            </TabsTrigger>
            <TabsTrigger value="users" className="flex-1">
              {t("bulkAccess.tabUsers")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="roles" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("bulkAccess.actionLabel")}</label>
              <Select
                value={roleMode}
                onValueChange={(v) => {
                  setRoleMode(v as "grant" | "revoke");
                  setSelectedRoleIds(new Set());
                  setRoleSearch("");
                  setRolePickerOpen(false);
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grant">{t("bulkAccess.grantAccess")}</SelectItem>
                  <SelectItem value="revoke">{t("bulkAccess.revokeAccess")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {roleMode === "revoke" && revocableRoles.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("bulkAccess.noRoleAccess")}</p>
            ) : (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t("bulkAccess.rolesLabel")}</label>
                  <ItemMultiPicker
                    items={filteredRoles.map((r) => ({
                      id: r.id,
                      label: r.displayName,
                      sublabel: initiativeIds.length > 1 ? r.initiativeName : undefined,
                    }))}
                    selectedIds={selectedRoleIds}
                    onToggle={toggleRole}
                    open={rolePickerOpen}
                    onOpenChange={setRolePickerOpen}
                    search={roleSearch}
                    onSearchChange={setRoleSearch}
                    placeholder={
                      roleMode === "grant"
                        ? t("bulkAccess.selectRoles")
                        : t("bulkAccess.selectRolesToRevoke")
                    }
                    emptyMessage={t("bulkAccess.noRolesFound")}
                    selectedMessage={(count) => t("bulkAccess.rolesSelected", { count })}
                    searchPlaceholder={t("bulkAccess.searchUsers")}
                  />
                </div>
                {roleMode === "grant" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("bulkAccess.permissionLevel")}</label>
                    <Select
                      value={roleLevel}
                      onValueChange={(v) => setRoleLevel(v as "read" | "write")}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("bulkAccess.canView")}</SelectItem>
                        <SelectItem value="write">{t("bulkAccess.canEdit")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </TabsContent>

          <TabsContent value="users" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t("bulkAccess.actionLabel")}</label>
              <Select
                value={userMode}
                onValueChange={(v) => {
                  setUserMode(v as "grant" | "revoke");
                  setSelectedUserIds(new Set());
                  setUserSearch("");
                  setUserPickerOpen(false);
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="grant">{t("bulkAccess.grantAccess")}</SelectItem>
                  <SelectItem value="revoke">{t("bulkAccess.revokeAccess")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {userMode === "revoke" && revocableUsers.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("bulkAccess.noUserAccess")}</p>
            ) : (
              <>
                <div className="space-y-2">
                  <label className="text-sm font-medium">{t("bulkAccess.usersLabel")}</label>
                  <UserMultiPicker
                    users={filteredUsers}
                    selectedIds={selectedUserIds}
                    onToggle={toggleUser}
                    open={userPickerOpen}
                    onOpenChange={setUserPickerOpen}
                    search={userSearch}
                    onSearchChange={setUserSearch}
                    placeholder={
                      userMode === "grant"
                        ? t("bulkAccess.selectUsers")
                        : t("bulkAccess.selectUsersToRevoke")
                    }
                    emptyMessage={t("bulkAccess.noUsersFound")}
                    selectedMessage={(count) => t("bulkAccess.usersSelected", { count })}
                    searchPlaceholder={t("bulkAccess.searchUsers")}
                  />
                </div>
                {userMode === "grant" && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">{t("bulkAccess.permissionLevel")}</label>
                    <Select
                      value={level}
                      onValueChange={(v) => setLevel(v as DocumentPermissionLevel)}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("bulkAccess.canView")}</SelectItem>
                        <SelectItem value="write">{t("bulkAccess.canEdit")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </TabsContent>
        </Tabs>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)} disabled={isPending}>
            {t("common:cancel")}
          </Button>
          {tab === "roles" ? (
            <Button
              onClick={() => void handleApplyRoles()}
              disabled={isPending || !canApplyRoles}
              variant={roleMode === "revoke" ? "destructive" : "default"}
            >
              {isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("bulkAccess.applying")}
                </>
              ) : roleMode === "grant" ? (
                t("bulkAccess.grantRoles", { count: selectedRoleCount })
              ) : (
                t("bulkAccess.revokeRoles", { count: selectedRoleCount })
              )}
            </Button>
          ) : (
            <Button
              onClick={() => void handleApply()}
              disabled={isPending || !canApplyUsers}
              variant={userMode === "revoke" ? "destructive" : "default"}
            >
              {isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("bulkAccess.applying")}
                </>
              ) : userMode === "grant" ? (
                t("bulkAccess.grantUsers", { count: selectedUserCount })
              ) : (
                t("bulkAccess.revokeUsers", { count: selectedUserCount })
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Reusable multi-select user picker
function UserMultiPicker({
  users,
  selectedIds,
  onToggle,
  open,
  onOpenChange,
  search,
  onSearchChange,
  placeholder,
  emptyMessage,
  selectedMessage,
  searchPlaceholder,
}: {
  users: SelectableUser[];
  selectedIds: Set<number>;
  onToggle: (id: number) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  search: string;
  onSearchChange: (value: string) => void;
  placeholder: string;
  emptyMessage: string;
  selectedMessage: (count: number) => string;
  searchPlaceholder: string;
}) {
  const selectedCount = selectedIds.size;

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "border-input ring-offset-background focus:ring-ring flex h-9 w-full items-center justify-between rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus:ring-1 focus:outline-none",
            selectedCount === 0 && "text-muted-foreground"
          )}
        >
          <span className="truncate">
            {selectedCount === 0 ? placeholder : selectedMessage(selectedCount)}
          </span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={search}
            onValueChange={onSearchChange}
          />
          <CommandList>
            <CommandGroup>
              {users.length === 0 ? (
                <div className="text-muted-foreground py-6 text-center text-sm">{emptyMessage}</div>
              ) : (
                users.map((user) => {
                  const isSelected = selectedIds.has(user.id);
                  return (
                    <CommandItem
                      key={user.id}
                      value={`user-${user.id}`}
                      onSelect={() => onToggle(user.id)}
                      className="cursor-pointer"
                    >
                      <div
                        className={cn(
                          "border-primary mr-2 flex h-4 w-4 items-center justify-center rounded-sm border",
                          isSelected
                            ? "bg-primary text-primary-foreground"
                            : "opacity-50 [&_svg]:invisible"
                        )}
                      >
                        <Check className="h-3 w-3" />
                      </div>
                      <div className="flex flex-col">
                        <span className="truncate text-sm">{user.name}</span>
                        {user.name !== user.email && (
                          <span className="text-muted-foreground truncate text-xs">
                            {user.email}
                          </span>
                        )}
                      </div>
                    </CommandItem>
                  );
                })
              )}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

// Reusable multi-select item picker (for roles)
function ItemMultiPicker({
  items,
  selectedIds,
  onToggle,
  open,
  onOpenChange,
  search,
  onSearchChange,
  placeholder,
  emptyMessage,
  selectedMessage,
  searchPlaceholder,
}: {
  items: { id: number; label: string; sublabel?: string }[];
  selectedIds: Set<number>;
  onToggle: (id: number) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  search: string;
  onSearchChange: (value: string) => void;
  placeholder: string;
  emptyMessage: string;
  selectedMessage: (count: number) => string;
  searchPlaceholder: string;
}) {
  const selectedCount = selectedIds.size;

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "border-input ring-offset-background focus:ring-ring flex h-9 w-full items-center justify-between rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus:ring-1 focus:outline-none",
            selectedCount === 0 && "text-muted-foreground"
          )}
        >
          <span className="truncate">
            {selectedCount === 0 ? placeholder : selectedMessage(selectedCount)}
          </span>
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={searchPlaceholder}
            value={search}
            onValueChange={onSearchChange}
          />
          <CommandList>
            <CommandGroup>
              {items.length === 0 ? (
                <div className="text-muted-foreground py-6 text-center text-sm">{emptyMessage}</div>
              ) : (
                items.map((item) => {
                  const isSelected = selectedIds.has(item.id);
                  return (
                    <CommandItem
                      key={item.id}
                      value={`item-${item.id}`}
                      onSelect={() => onToggle(item.id)}
                      className="cursor-pointer"
                    >
                      <div
                        className={cn(
                          "border-primary mr-2 flex h-4 w-4 items-center justify-center rounded-sm border",
                          isSelected
                            ? "bg-primary text-primary-foreground"
                            : "opacity-50 [&_svg]:invisible"
                        )}
                      >
                        <Check className="h-3 w-3" />
                      </div>
                      <div className="flex flex-col">
                        <span className="truncate text-sm">{item.label}</span>
                        {item.sublabel && (
                          <span className="text-muted-foreground truncate text-xs">
                            {item.sublabel}
                          </span>
                        )}
                      </div>
                    </CommandItem>
                  );
                })
              )}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
