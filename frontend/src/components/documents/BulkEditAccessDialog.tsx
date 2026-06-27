import { useQueries } from "@tanstack/react-query";
import { Check, ChevronDown, Loader2 } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut } from "@/api/generated/documents/documents";
import type {
  DocumentSummary,
  InitiativeRoleRead,
  ResourceGrantSchema,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGetQueryKey,
  listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet,
} from "@/api/generated/initiatives/initiatives";
import { invalidateAllDocuments } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { useAuth } from "@/hooks/useAuth";
import { useInitiatives } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { cn } from "@/lib/utils";
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
  const { t } = useTranslation(["documents", "common", "access"]);
  const guildId = useActiveGuildId();
  const { user: currentUser } = useAuth();
  const [tab, setTab] = useState<"people" | "roles" | "all">("people");
  const [isPending, setIsPending] = useState(false);

  // Individual people state
  const [userMode, setUserMode] = useState<"grant" | "revoke">("grant");
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [level, setLevel] = useState<"read" | "write">("read");
  const [userPickerOpen, setUserPickerOpen] = useState(false);
  const [userSearch, setUserSearch] = useState("");

  // Role state
  const [roleMode, setRoleMode] = useState<"grant" | "revoke">("grant");
  const [selectedRoleIds, setSelectedRoleIds] = useState<Set<number>>(new Set());
  const [roleLevel, setRoleLevel] = useState<"read" | "write">("read");
  const [rolePickerOpen, setRolePickerOpen] = useState(false);
  const [roleSearch, setRoleSearch] = useState("");

  // All-initiative-members state (the "all members" share mode, applied in bulk)
  const [allMode, setAllMode] = useState<"share" | "remove">("share");
  const [allLevel, setAllLevel] = useState<"read" | "write">("read");

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
      queryKey: getListInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGetQueryKey(
        guildId,
        id
      ),
      queryFn: () =>
        listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet(
          guildId,
          id
        ) as unknown as Promise<InitiativeRoleRead[]>,
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

  // Resolve a role id to its display info (from the fetched initiative roles).
  const rolesById = useMemo(() => {
    const map = new Map<number, SelectableRole>();
    for (const role of availableRoles) map.set(role.id, role);
    return map;
  }, [availableRoles]);

  // Roles that are currently granted on at least one selected document (for revoke)
  const revocableRoles = useMemo(() => {
    const roleMap = new Map<number, SelectableRole>();
    for (const doc of documents) {
      for (const grant of doc.grants ?? []) {
        if (grant.role_id == null || roleMap.has(grant.role_id)) continue;
        const known = rolesById.get(grant.role_id);
        roleMap.set(grant.role_id, {
          id: grant.role_id,
          name: known?.name ?? `role-${grant.role_id}`,
          displayName: known?.displayName ?? `Role ${grant.role_id}`,
          initiativeId: doc.initiative_id,
          initiativeName: doc.initiative?.name ?? `Initiative ${doc.initiative_id}`,
        });
      }
    }
    return Array.from(roleMap.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [documents, rolesById]);

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

  // Build list of people from initiatives the selected documents belong to
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

  // People who have non-owner access on at least one selected document (for revoke)
  const revocableUsers = useMemo(() => {
    const userMap = new Map<number, SelectableUser>();
    for (const doc of documents) {
      for (const grant of doc.grants ?? []) {
        const userId = grant.user_id;
        if (
          userId != null &&
          grant.level !== "owner" &&
          userId !== currentUser?.id &&
          !userMap.has(userId)
        ) {
          // Try to find user info from initiative members
          const member = doc.initiative?.members?.find((m) => m.user.id === userId);
          userMap.set(userId, {
            id: userId,
            name: member?.user?.full_name || member?.user?.email || `User ${userId}`,
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
    setTab("people");
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
    setAllMode("share");
    setAllLevel("read");
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
      const userIds = new Set(selectedUserIds);

      // Rebuild each document's non-owner grant list (the owner is preserved
      // server-side regardless of what we send).
      await Promise.all(
        documents.map((doc) => {
          const existing = (doc.grants ?? []).filter((g) => g.level !== "owner");
          let next: ResourceGrantSchema[];
          if (userMode === "grant") {
            // Granting specific people switches the doc to "restricted" mode, so
            // drop any "all initiative members" grant — ShareControl can't
            // represent a mixed all-members + per-grantee list and would
            // silently discard it on the next save. Also drop any existing
            // per-user grant for the targeted people, then add them back at the
            // chosen level.
            next = existing.filter(
              (g) => !g.all_initiative_members && (g.user_id == null || !userIds.has(g.user_id))
            );
            for (const userId of userIds) {
              next.push({ user_id: userId, level });
            }
          } else {
            next = existing.filter((g) => g.user_id == null || !userIds.has(g.user_id));
          }
          return setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(guildId, doc.id, next);
        })
      );

      if (userMode === "grant") {
        toast.success(t("bulkAccess.userAccessGranted", { count: documents.length }));
      } else {
        toast.success(t("bulkAccess.userAccessRevoked", { count: documents.length }));
      }

      void invalidateAllDocuments();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(getErrorMessage(error, "documents:bulkAccess.updateError"));
    } finally {
      setIsPending(false);
    }
  }, [
    selectedUserIds,
    userMode,
    documents,
    level,
    resetState,
    onOpenChange,
    onSuccess,
    t,
    guildId,
  ]);

  const handleApplyRoles = useCallback(async () => {
    if (selectedRoleIds.size === 0) return;

    setIsPending(true);
    try {
      const roleIds = [...selectedRoleIds];

      const affectedDocIds = new Set<number>();
      const updates: Promise<unknown>[] = [];

      for (const doc of documents) {
        const existing = (doc.grants ?? []).filter((g) => g.level !== "owner");
        const grantedRoleIds = new Set(
          existing.filter((g) => g.role_id != null).map((g) => g.role_id as number)
        );

        if (roleMode === "grant") {
          // Only grant roles that belong to this doc's initiative and aren't already granted.
          const docRoleIds = availableRoles
            .filter((r) => r.initiativeId === doc.initiative_id && roleIds.includes(r.id))
            .map((r) => r.id)
            .filter((id) => !grantedRoleIds.has(id));
          if (docRoleIds.length === 0) continue;
          affectedDocIds.add(doc.id);
          const next: ResourceGrantSchema[] = [
            // Granting specific roles switches the doc to "restricted" mode;
            // drop any "all initiative members" grant so ShareControl doesn't
            // receive a mixed list it can't display (and would silently discard
            // on the next save).
            ...existing.filter((g) => !g.all_initiative_members),
            ...docRoleIds.map((id) => ({ role_id: id, level: roleLevel })),
          ];
          updates.push(
            setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(guildId, doc.id, next)
          );
        } else {
          const toRevoke = roleIds.filter((id) => grantedRoleIds.has(id));
          if (toRevoke.length === 0) continue;
          affectedDocIds.add(doc.id);
          const revokeSet = new Set(toRevoke);
          const next = existing.filter((g) => g.role_id == null || !revokeSet.has(g.role_id));
          updates.push(
            setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(guildId, doc.id, next)
          );
        }
      }

      await Promise.all(updates);
      const affected = affectedDocIds.size;
      if (affected === 0) {
        toast.info(t("bulkAccess.rolesAlreadyAssigned"));
      } else if (roleMode === "grant") {
        toast.success(t("bulkAccess.roleAccessGranted", { count: affected }));
      } else {
        toast.success(t("bulkAccess.roleAccessRevoked", { count: affected }));
      }

      void invalidateAllDocuments();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(getErrorMessage(error, "documents:bulkAccess.roleUpdateError"));
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
    guildId,
  ]);

  const handleApplyAllMembers = useCallback(async () => {
    setIsPending(true);
    try {
      await Promise.all(
        documents.map((doc) => {
          let next: ResourceGrantSchema[];
          if (allMode === "share") {
            // Switch every selected doc to "all members" mode: a single
            // all-members grant. Per-person and per-role grants are dropped so
            // the doc has one coherent share mode (ShareControl can't render a
            // mixed all-members + restricted list). The owner is preserved
            // server-side, so we don't send it.
            next = [{ all_initiative_members: true, level: allLevel }];
          } else {
            // Remove all-members access only; keep existing restricted grants.
            next = (doc.grants ?? []).filter(
              (g) => g.level !== "owner" && !g.all_initiative_members
            );
          }
          return setDocumentGrantsApiV1GGuildIdDocumentsDocumentIdGrantsPut(guildId, doc.id, next);
        })
      );

      toast.success(
        allMode === "share"
          ? t("bulkAccess.allMembersShared", { count: documents.length })
          : t("bulkAccess.allMembersRemoved", { count: documents.length })
      );

      void invalidateAllDocuments();
      resetState();
      onOpenChange(false);
      onSuccess();
    } catch (error) {
      toast.error(getErrorMessage(error, "documents:bulkAccess.updateError"));
    } finally {
      setIsPending(false);
    }
  }, [allMode, allLevel, documents, resetState, onOpenChange, onSuccess, t, guildId]);

  const selectedUserCount = selectedUserIds.size;
  const selectedRoleCount = selectedRoleIds.size;
  const canApplyUsers = selectedUserCount > 0;
  const canApplyRoles = selectedRoleCount > 0;

  const docCount = documents.length;
  const dialogDescription = useMemo(() => {
    if (tab === "roles") {
      return roleMode === "grant"
        ? t("bulkAccess.descriptionGrant", { count: docCount })
        : t("bulkAccess.descriptionRevoke", { count: docCount });
    }
    if (tab === "people") {
      return userMode === "grant"
        ? t("bulkAccess.descriptionGrantUser", { count: docCount })
        : t("bulkAccess.descriptionRevokeUser", { count: docCount });
    }
    return allMode === "share"
      ? t("bulkAccess.descriptionAllShare", { count: docCount })
      : t("bulkAccess.descriptionAllRemove", { count: docCount });
  }, [tab, roleMode, userMode, allMode, docCount, t]);

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
            setTab(v as "people" | "roles" | "all");
            setSelectedUserIds(new Set());
            setUserSearch("");
            setUserPickerOpen(false);
            setSelectedRoleIds(new Set());
            setRoleSearch("");
            setRolePickerOpen(false);
          }}
        >
          <TabsList className="w-full">
            <TabsTrigger value="people" className="flex-1">
              {t("access:share.people")}
            </TabsTrigger>
            <TabsTrigger value="roles" className="flex-1">
              {t("access:share.roles")}
            </TabsTrigger>
            <TabsTrigger value="all" className="flex-1">
              {t("bulkAccess.tabAllMembers")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="people" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label htmlFor="userMode" className="font-medium text-sm">
                {t("bulkAccess.actionLabel")}
              </label>
              <Select
                value={userMode}
                onValueChange={(v) => {
                  setUserMode(v as "grant" | "revoke");
                  setSelectedUserIds(new Set());
                  setUserSearch("");
                  setUserPickerOpen(false);
                }}
              >
                <SelectTrigger id="userMode">
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
                  <label htmlFor="userPicker" className="font-medium text-sm">
                    {t("access:share.people")}
                  </label>
                  <UserMultiPicker
                    id="userPicker"
                    users={filteredUsers}
                    selectedIds={selectedUserIds}
                    onToggle={toggleUser}
                    open={userPickerOpen}
                    onOpenChange={setUserPickerOpen}
                    search={userSearch}
                    onSearchChange={setUserSearch}
                    placeholder={
                      userMode === "grant"
                        ? t("bulkAccess.selectPeople")
                        : t("bulkAccess.selectPeopleToRevoke")
                    }
                    emptyMessage={t("access:share.noPeople")}
                    selectedMessage={(count) => t("bulkAccess.peopleSelected", { count })}
                    searchPlaceholder={t("access:share.searchPeople")}
                  />
                </div>
                {userMode === "grant" && (
                  <div className="space-y-2">
                    <label htmlFor="userLevel" className="font-medium text-sm">
                      {t("bulkAccess.permissionLevel")}
                    </label>
                    <Select value={level} onValueChange={(v) => setLevel(v as "read" | "write")}>
                      <SelectTrigger id="userLevel">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("access:share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("access:share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </TabsContent>

          <TabsContent value="roles" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label htmlFor="roleMode" className="font-medium text-sm">
                {t("bulkAccess.actionLabel")}
              </label>
              <Select
                value={roleMode}
                onValueChange={(v) => {
                  setRoleMode(v as "grant" | "revoke");
                  setSelectedRoleIds(new Set());
                  setRoleSearch("");
                  setRolePickerOpen(false);
                }}
              >
                <SelectTrigger id="roleMode">
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
                  <label htmlFor="rolePicker" className="font-medium text-sm">
                    {t("access:share.roles")}
                  </label>
                  <ItemMultiPicker
                    id="rolePicker"
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
                    emptyMessage={t("access:share.noRoles")}
                    selectedMessage={(count) => t("bulkAccess.rolesSelected", { count })}
                    searchPlaceholder={t("access:share.searchRoles")}
                  />
                </div>
                {roleMode === "grant" && (
                  <div className="space-y-2">
                    <label htmlFor="roleLevel" className="font-medium text-sm">
                      {t("bulkAccess.permissionLevel")}
                    </label>
                    <Select
                      value={roleLevel}
                      onValueChange={(v) => setRoleLevel(v as "read" | "write")}
                    >
                      <SelectTrigger id="roleLevel">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("access:share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("access:share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </>
            )}
          </TabsContent>

          <TabsContent value="all" className="mt-4 space-y-3">
            <div className="space-y-2">
              <label htmlFor="allMode" className="font-medium text-sm">
                {t("bulkAccess.actionLabel")}
              </label>
              <Select value={allMode} onValueChange={(v) => setAllMode(v as "share" | "remove")}>
                <SelectTrigger id="allMode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="share">{t("bulkAccess.shareAllMembers")}</SelectItem>
                  <SelectItem value="remove">{t("bulkAccess.removeAllMembersAccess")}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {allMode === "share" && (
              <div className="space-y-2">
                <label htmlFor="allLevel" className="font-medium text-sm">
                  {t("bulkAccess.permissionLevel")}
                </label>
                <Select value={allLevel} onValueChange={(v) => setAllLevel(v as "read" | "write")}>
                  <SelectTrigger id="allLevel">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="read">{t("access:share.viewer")}</SelectItem>
                    <SelectItem value="write">{t("access:share.editor")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}

            <p className="text-muted-foreground text-xs">
              {allMode === "share"
                ? t("bulkAccess.shareAllMembersHint")
                : t("bulkAccess.removeAllMembersHint")}
            </p>
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
          ) : tab === "people" ? (
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
                t("bulkAccess.grantPeople", { count: selectedUserCount })
              ) : (
                t("bulkAccess.revokePeople", { count: selectedUserCount })
              )}
            </Button>
          ) : (
            <Button
              onClick={() => void handleApplyAllMembers()}
              disabled={isPending}
              variant={allMode === "remove" ? "destructive" : "default"}
            >
              {isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("bulkAccess.applying")}
                </>
              ) : allMode === "share" ? (
                t("bulkAccess.shareAllMembers")
              ) : (
                t("bulkAccess.removeAllMembersAccess")
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
  id,
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
  id?: string;
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
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "flex h-9 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring",
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
                <div className="py-6 text-center text-muted-foreground text-sm">{emptyMessage}</div>
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
                          "mr-2 flex h-4 w-4 items-center justify-center rounded-sm border border-primary",
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
                          <span className="truncate text-muted-foreground text-xs">
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
  id,
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
  id?: string;
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
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "flex h-9 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring",
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
                <div className="py-6 text-center text-muted-foreground text-sm">{emptyMessage}</div>
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
                          "mr-2 flex h-4 w-4 items-center justify-center rounded-sm border border-primary",
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
                          <span className="truncate text-muted-foreground text-xs">
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
