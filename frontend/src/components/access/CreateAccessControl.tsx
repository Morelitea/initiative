import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
import { getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey } from "@/api/generated/initiatives/initiatives";
import { useAuth } from "@/hooks/useAuth";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { InitiativeRead, InitiativeRoleRead } from "@/types/api";

// ─── Exported types ──────────────────────────────────────────────────────────

export interface RoleGrant {
  initiative_role_id: number;
  level: "read" | "write";
}

export interface UserGrant {
  user_id: number;
  level: "read" | "write";
}

// ─── Props ───────────────────────────────────────────────────────────────────

interface CreateAccessControlProps {
  initiativeId: number | null;
  roleGrants: RoleGrant[];
  onRoleGrantsChange: (grants: RoleGrant[]) => void;
  userGrants: UserGrant[];
  onUserGrantsChange: (grants: UserGrant[]) => void;
  addAllMembersDefault?: boolean;
  onLoadingChange?: (loading: boolean) => void;
}

// ─── Component ───────────────────────────────────────────────────────────────

export const CreateAccessControl = ({
  initiativeId,
  roleGrants,
  onRoleGrantsChange,
  userGrants,
  onUserGrantsChange,
  addAllMembersDefault = false,
  onLoadingChange,
}: CreateAccessControlProps) => {
  const { t } = useTranslation("common");
  const { user: currentUser } = useAuth();

  // ── Data fetching ────────────────────────────────────────────────────────

  const { data: roles = [] } = useInitiativeRoles(initiativeId);

  const { data: initiative, isLoading: initiativeLoading } = useQuery<InitiativeRead>({
    // Use the generated query key so cache invalidations align with other consumers
    queryKey: getGetInitiativeApiV1InitiativesInitiativeIdGetQueryKey(initiativeId!),
    queryFn: async () => {
      const response = await apiClient.get<InitiativeRead>(`/initiatives/${initiativeId}`);
      return response.data;
    },
    enabled: !!initiativeId,
  });

  useEffect(() => {
    onLoadingChange?.(initiativeLoading);
  }, [initiativeLoading, onLoadingChange]);

  const members = useMemo(() => {
    if (!initiative?.members) return [];
    return initiative.members.filter((m) => m.user.id !== currentUser?.id);
  }, [initiative, currentUser]);

  // ── "Add all members" state ──────────────────────────────────────────────

  const [addAllMembers, setAddAllMembers] = useState(addAllMembersDefault);

  // Sync internal state if the parent changes addAllMembersDefault
  useEffect(() => {
    setAddAllMembers(addAllMembersDefault);
  }, [addAllMembersDefault]);

  // When initiative changes or members load, auto-populate if addAllMembers is active
  useEffect(() => {
    if (addAllMembers && members.length > 0) {
      const allGrants: UserGrant[] = members.map((m) => ({
        user_id: m.user.id,
        level: "read" as const,
      }));
      onUserGrantsChange(allGrants);
    }
    // Only react to members loading or addAllMembers toggling, not onUserGrantsChange itself
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addAllMembers, members]);

  const handleAddAllMembersToggle = useCallback(
    (checked: boolean) => {
      setAddAllMembers(checked);
      if (!checked) {
        // Clear auto-populated grants
        onUserGrantsChange([]);
      }
      // If checked, the effect above will populate grants when members are available
    },
    [onUserGrantsChange]
  );

  // ── Role picker state ────────────────────────────────────────────────────

  const [selectedRoleIds, setSelectedRoleIds] = useState<Set<number>>(new Set());
  const [roleLevel, setRoleLevel] = useState<"read" | "write">("read");
  const [rolePickerOpen, setRolePickerOpen] = useState(false);
  const [roleSearch, setRoleSearch] = useState("");

  const grantedRoleIds = useMemo(
    () => new Set(roleGrants.map((g) => g.initiative_role_id)),
    [roleGrants]
  );

  const availableRoles = useMemo(() => {
    return roles.filter((r) => !grantedRoleIds.has(r.id));
  }, [roles, grantedRoleIds]);

  const filteredRoles = useMemo(() => {
    if (!roleSearch.trim()) return availableRoles;
    const lower = roleSearch.toLowerCase();
    return availableRoles.filter((r) => r.display_name.toLowerCase().includes(lower));
  }, [availableRoles, roleSearch]);

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

  const handleAddRoles = useCallback(() => {
    if (selectedRoleIds.size === 0) return;
    const newGrants: RoleGrant[] = [...selectedRoleIds].map((id) => ({
      initiative_role_id: id,
      level: roleLevel,
    }));
    onRoleGrantsChange([...roleGrants, ...newGrants]);
    setSelectedRoleIds(new Set());
    setRoleSearch("");
    setRolePickerOpen(false);
  }, [selectedRoleIds, roleLevel, roleGrants, onRoleGrantsChange]);

  const removeRoleGrant = useCallback(
    (roleId: number) => {
      onRoleGrantsChange(roleGrants.filter((g) => g.initiative_role_id !== roleId));
    },
    [roleGrants, onRoleGrantsChange]
  );

  // ── User picker state ────────────────────────────────────────────────────

  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [userLevel, setUserLevel] = useState<"read" | "write">("read");
  const [userPickerOpen, setUserPickerOpen] = useState(false);
  const [userSearch, setUserSearch] = useState("");

  const grantedUserIds = useMemo(() => new Set(userGrants.map((g) => g.user_id)), [userGrants]);

  const availableUsers = useMemo(() => {
    return members.filter((m) => !grantedUserIds.has(m.user.id));
  }, [members, grantedUserIds]);

  const filteredUsers = useMemo(() => {
    if (!userSearch.trim()) return availableUsers;
    const lower = userSearch.toLowerCase();
    return availableUsers.filter(
      (m) =>
        (m.user.full_name?.toLowerCase().includes(lower) ?? false) ||
        m.user.email.toLowerCase().includes(lower)
    );
  }, [availableUsers, userSearch]);

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

  const handleAddUsers = useCallback(() => {
    if (selectedUserIds.size === 0) return;
    const newGrants: UserGrant[] = [...selectedUserIds].map((id) => ({
      user_id: id,
      level: userLevel,
    }));
    onUserGrantsChange([...userGrants, ...newGrants]);
    setSelectedUserIds(new Set());
    setUserSearch("");
    setUserPickerOpen(false);
  }, [selectedUserIds, userLevel, userGrants, onUserGrantsChange]);

  const removeUserGrant = useCallback(
    (userId: number) => {
      setAddAllMembers(false); // manual removal opts out of auto-populate
      onUserGrantsChange(userGrants.filter((g) => g.user_id !== userId));
    },
    [userGrants, onUserGrantsChange]
  );

  // ── Lookup helpers for displaying grant badges ───────────────────────────

  const roleDisplayName = useCallback(
    (roleId: number): string => {
      const role = roles.find((r: InitiativeRoleRead) => r.id === roleId);
      return role?.display_name ?? `Role ${roleId}`;
    },
    [roles]
  );

  const userDisplayName = useCallback(
    (userId: number): string => {
      const member = initiative?.members.find((m) => m.user.id === userId);
      return member?.user.full_name || member?.user.email || `User ${userId}`;
    },
    [initiative]
  );

  // ── Disabled state ──────────────────────────────────────────────────────

  if (initiativeId === null) {
    return <p className="text-muted-foreground text-sm">{t("createAccess.noInitiative")}</p>;
  }

  return (
    <div className="space-y-6">
      {/* ── Section 1: Role Access ──────────────────────────────────────── */}
      <div className="space-y-3">
        <div>
          <Label className="text-sm font-medium">{t("createAccess.roleAccess")}</Label>
          <p className="text-muted-foreground text-xs">{t("createAccess.roleAccessHint")}</p>
        </div>

        <div className="flex items-end gap-2">
          {/* Role picker */}
          <div className="min-w-0 flex-1">
            <Popover open={rolePickerOpen} onOpenChange={setRolePickerOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  role="combobox"
                  aria-expanded={rolePickerOpen}
                  className={cn(
                    "border-input ring-offset-background focus:ring-ring flex h-9 w-full items-center justify-between rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus:ring-1 focus:outline-none",
                    selectedRoleIds.size === 0 && "text-muted-foreground"
                  )}
                >
                  <span className="truncate">
                    {selectedRoleIds.size > 0
                      ? t("countSelected", { count: selectedRoleIds.size })
                      : t("createAccess.selectRoles")}
                  </span>
                  <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 p-0" align="start">
                <Command shouldFilter={false}>
                  <CommandInput
                    placeholder={t("createAccess.searchRoles")}
                    value={roleSearch}
                    onValueChange={setRoleSearch}
                  />
                  <CommandList>
                    <CommandEmpty>{t("createAccess.noRoles")}</CommandEmpty>
                    <CommandGroup>
                      {filteredRoles.map((role) => {
                        const isSelected = selectedRoleIds.has(role.id);
                        return (
                          <CommandItem
                            key={role.id}
                            value={`role-${role.id}`}
                            onSelect={() => toggleRole(role.id)}
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
                            <span className="truncate">{role.display_name}</span>
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>

          {/* Level selector */}
          <Select value={roleLevel} onValueChange={(v) => setRoleLevel(v as "read" | "write")}>
            <SelectTrigger className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">{t("createAccess.canView")}</SelectItem>
              <SelectItem value="write">{t("createAccess.canEdit")}</SelectItem>
            </SelectContent>
          </Select>

          {/* Add button */}
          <Button
            type="button"
            size="sm"
            onClick={handleAddRoles}
            disabled={selectedRoleIds.size === 0}
          >
            {t("createAccess.add")}
          </Button>
        </div>

        {/* Pending role grants */}
        {roleGrants.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {roleGrants.map((grant) => (
              <Badge key={grant.initiative_role_id} variant="secondary" className="gap-1 pr-1">
                <span>{roleDisplayName(grant.initiative_role_id)}</span>
                <span className="text-muted-foreground text-[10px]">
                  ({grant.level === "read" ? t("createAccess.canView") : t("createAccess.canEdit")})
                </span>
                <button
                  type="button"
                  onClick={() => removeRoleGrant(grant.initiative_role_id)}
                  className="hover:bg-muted ml-0.5 rounded p-0.5"
                  aria-label={t("createAccess.remove")}
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* ── Section 2: User Access ──────────────────────────────────────── */}
      <div className="space-y-3">
        <div>
          <Label className="text-sm font-medium">{t("createAccess.userAccess")}</Label>
          <p className="text-muted-foreground text-xs">{t("createAccess.userAccessHint")}</p>
        </div>

        {/* Add all members checkbox */}
        <div className="flex items-start gap-2">
          <Checkbox
            id="add-all-members"
            checked={addAllMembers}
            onCheckedChange={(checked) => handleAddAllMembersToggle(checked === true)}
          />
          <div className="grid gap-0.5 leading-none">
            <Label htmlFor="add-all-members" className="cursor-pointer text-sm">
              {t("createAccess.addAllMembers")}
            </Label>
            <p className="text-muted-foreground text-xs">{t("createAccess.addAllMembersHint")}</p>
          </div>
        </div>

        <div className="flex items-end gap-2">
          {/* User picker */}
          <div className="min-w-0 flex-1">
            <Popover open={userPickerOpen} onOpenChange={setUserPickerOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  role="combobox"
                  aria-expanded={userPickerOpen}
                  className={cn(
                    "border-input ring-offset-background focus:ring-ring flex h-9 w-full items-center justify-between rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus:ring-1 focus:outline-none",
                    selectedUserIds.size === 0 && "text-muted-foreground"
                  )}
                >
                  <span className="truncate">
                    {selectedUserIds.size > 0
                      ? t("countSelected", { count: selectedUserIds.size })
                      : t("createAccess.selectMembers")}
                  </span>
                  <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 p-0" align="start">
                <Command shouldFilter={false}>
                  <CommandInput
                    placeholder={t("createAccess.searchMembers")}
                    value={userSearch}
                    onValueChange={setUserSearch}
                  />
                  <CommandList>
                    <CommandEmpty>{t("createAccess.noMembers")}</CommandEmpty>
                    <CommandGroup>
                      {filteredUsers.map((member) => {
                        const isSelected = selectedUserIds.has(member.user.id);
                        const displayName = member.user.full_name || member.user.email;
                        return (
                          <CommandItem
                            key={member.user.id}
                            value={`user-${member.user.id}`}
                            onSelect={() => toggleUser(member.user.id)}
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
                              <span className="truncate text-sm">{displayName}</span>
                              {member.user.full_name &&
                                member.user.full_name !== member.user.email && (
                                  <span className="text-muted-foreground truncate text-xs">
                                    {member.user.email}
                                  </span>
                                )}
                            </div>
                          </CommandItem>
                        );
                      })}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>

          {/* Level selector */}
          <Select value={userLevel} onValueChange={(v) => setUserLevel(v as "read" | "write")}>
            <SelectTrigger className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">{t("createAccess.canView")}</SelectItem>
              <SelectItem value="write">{t("createAccess.canEdit")}</SelectItem>
            </SelectContent>
          </Select>

          {/* Add button */}
          <Button
            type="button"
            size="sm"
            onClick={handleAddUsers}
            disabled={selectedUserIds.size === 0}
          >
            {t("createAccess.add")}
          </Button>
        </div>

        {/* Pending user grants */}
        {userGrants.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {userGrants.map((grant) => (
              <Badge key={grant.user_id} variant="secondary" className="gap-1 pr-1">
                <span>{userDisplayName(grant.user_id)}</span>
                <span className="text-muted-foreground text-[10px]">
                  ({grant.level === "read" ? t("createAccess.canView") : t("createAccess.canEdit")})
                </span>
                <button
                  type="button"
                  onClick={() => removeUserGrant(grant.user_id)}
                  className="hover:bg-muted ml-0.5 rounded p-0.5"
                  aria-label={t("createAccess.remove")}
                >
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
