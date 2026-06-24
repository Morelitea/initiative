import { ChevronDown, Lock, Users, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiative } from "@/hooks/useInitiatives";
import { cn } from "@/lib/utils";

// ─── Props ───────────────────────────────────────────────────────────────────

export interface ShareControlProps {
  initiativeId: number | null;
  /** Full grant list for the resource (may include the owner-level grant). */
  grants: ResourceGrantSchema[];
  /** Called with the full NON-owner grant list to persist. */
  onChange: (grants: ResourceGrantSchema[]) => void;
  /** When given, a fixed, non-editable "Owner" row is shown. Omit in create. */
  ownerId?: number | null;
  /** Viewer can't manage, or a save is in flight. */
  disabled?: boolean;
}

type ShareLevel = "read" | "write";

// ─── Component ───────────────────────────────────────────────────────────────

export const ShareControl = ({
  initiativeId,
  grants,
  onChange,
  ownerId,
  disabled = false,
}: ShareControlProps) => {
  const { t } = useTranslation("access");

  const { data: roles = [] } = useInitiativeRoles(initiativeId);
  const { data: initiative } = useInitiative(initiativeId);

  const members = useMemo(() => initiative?.members ?? [], [initiative?.members]);

  // ── Derived grant buckets ────────────────────────────────────────────────

  const allMembersGrant = useMemo(() => grants.find((g) => g.all_initiative_members), [grants]);
  const mode: "all" | "restricted" = allMembersGrant ? "all" : "restricted";

  const userGrants = useMemo(
    () => grants.filter((g) => g.user_id != null && g.level !== "owner"),
    [grants]
  );
  const roleGrants = useMemo(() => grants.filter((g) => g.role_id != null), [grants]);

  // Roles with "Full access" (override_share_restrictions) always view/edit
  // everything in the initiative, so they show as a locked Editor that can't be
  // removed or downgraded — even in Restricted mode. It's implied by the role
  // (not a stored grant), so it's injected here and never emitted in onChange.
  const fullAccessRoles = useMemo(
    () => roles.filter((r) => r.override_share_restrictions),
    [roles]
  );
  const fullAccessRoleIds = useMemo(
    () => new Set(fullAccessRoles.map((r) => r.id)),
    [fullAccessRoles]
  );
  // Real role grants minus any full-access role (rendered as locked instead, so
  // a stray stored grant to it doesn't double-render or look editable).
  const editableRoleGrants = useMemo(
    () => roleGrants.filter((g) => !fullAccessRoleIds.has(g.role_id as number)),
    [roleGrants, fullAccessRoleIds]
  );

  const allLevel: ShareLevel = allMembersGrant?.level === "write" ? "write" : "read";

  // ── Lookup helpers ───────────────────────────────────────────────────────

  const userDisplayName = useCallback(
    (userId: number): string => {
      const member = members.find((m) => m.user.id === userId);
      return member?.user.full_name?.trim() || member?.user.email || `User ${userId}`;
    },
    [members]
  );

  const userEmail = useCallback(
    (userId: number): string | null => {
      const member = members.find((m) => m.user.id === userId);
      const email = member?.user.email;
      const name = member?.user.full_name?.trim();
      return email && email !== name ? email : null;
    },
    [members]
  );

  const roleDisplayName = useCallback(
    (roleId: number): string => {
      const role = roles.find((r) => r.id === roleId);
      return role?.display_name ?? `Role ${roleId}`;
    },
    [roles]
  );

  const ownerDisplayName = useMemo(() => {
    if (ownerId == null) return null;
    return userDisplayName(ownerId);
  }, [ownerId, userDisplayName]);

  // ── Pickable (not-yet-granted) members / roles ───────────────────────────

  const grantedUserIds = useMemo(() => new Set(userGrants.map((g) => g.user_id)), [userGrants]);
  const grantedRoleIds = useMemo(() => new Set(roleGrants.map((g) => g.role_id)), [roleGrants]);

  const availableMembers = useMemo(
    () => members.filter((m) => m.user.id !== ownerId && !grantedUserIds.has(m.user.id)),
    [members, ownerId, grantedUserIds]
  );
  const availableRoles = useMemo(
    // Full-access roles already have access (shown locked), so they're not pickable.
    () => roles.filter((r) => !grantedRoleIds.has(r.id) && !fullAccessRoleIds.has(r.id)),
    [roles, grantedRoleIds, fullAccessRoleIds]
  );

  // ── Mutators ─────────────────────────────────────────────────────────────

  const setMode = useCallback(
    (next: "all" | "restricted") => {
      if (next === "all") {
        onChange([{ all_initiative_members: true, level: "read" }]);
      } else {
        onChange([...userGrants, ...roleGrants]);
      }
    },
    [onChange, userGrants, roleGrants]
  );

  const setAllLevel = useCallback(
    (level: ShareLevel) => {
      onChange([{ all_initiative_members: true, level }]);
    },
    [onChange]
  );

  const setUserLevel = useCallback(
    (userId: number, level: ShareLevel) => {
      onChange([
        ...userGrants.map((g) => (g.user_id === userId ? { ...g, level } : g)),
        ...roleGrants,
      ]);
    },
    [onChange, userGrants, roleGrants]
  );

  const removeUser = useCallback(
    (userId: number) => {
      onChange([...userGrants.filter((g) => g.user_id !== userId), ...roleGrants]);
    },
    [onChange, userGrants, roleGrants]
  );

  const addUser = useCallback(
    (userId: number) => {
      onChange([...userGrants, { user_id: userId, level: "read" }, ...roleGrants]);
    },
    [onChange, userGrants, roleGrants]
  );

  const setRoleLevel = useCallback(
    (roleId: number, level: ShareLevel) => {
      onChange([
        ...userGrants,
        ...roleGrants.map((g) => (g.role_id === roleId ? { ...g, level } : g)),
      ]);
    },
    [onChange, userGrants, roleGrants]
  );

  const removeRole = useCallback(
    (roleId: number) => {
      onChange([...userGrants, ...roleGrants.filter((g) => g.role_id !== roleId)]);
    },
    [onChange, userGrants, roleGrants]
  );

  const addRole = useCallback(
    (roleId: number) => {
      onChange([...userGrants, ...roleGrants, { role_id: roleId, level: "read" }]);
    },
    [onChange, userGrants, roleGrants]
  );

  // ── Picker open state ────────────────────────────────────────────────────

  const [modePickerOpen, setModePickerOpen] = useState(false);
  const [peoplePickerOpen, setPeoplePickerOpen] = useState(false);
  const [rolePickerOpen, setRolePickerOpen] = useState(false);

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* ── Share ─────────────────────────────────────────────────────── */}
      <div className="space-y-2">
        <Label className="font-medium text-sm">{t("share.title")}</Label>
        <div
          className={cn(
            "flex items-center gap-3 rounded-lg border px-3 py-2.5",
            mode === "all"
              ? "border-green-200 bg-green-50 dark:border-green-900/40 dark:bg-green-950/30"
              : "bg-muted/40"
          )}
        >
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
              mode === "all"
                ? "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300"
                : "bg-muted text-muted-foreground"
            )}
          >
            {mode === "all" ? <Users className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
          </div>

          <Popover open={modePickerOpen} onOpenChange={setModePickerOpen}>
            <PopoverTrigger asChild>
              <button
                type="button"
                disabled={disabled}
                className="flex min-w-0 flex-1 flex-col text-left focus:outline-none disabled:cursor-not-allowed"
              >
                <span className="flex items-center gap-1">
                  <span className="truncate font-medium text-sm">
                    {mode === "all" ? t("share.allMembers") : t("share.restricted")}
                  </span>
                  <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
                </span>
                <span className="truncate text-muted-foreground text-xs">
                  {mode === "all" ? t("share.allMembersHint") : t("share.restrictedHint")}
                </span>
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72 p-1">
              {(["all", "restricted"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    setMode(m);
                    setModePickerOpen(false);
                  }}
                  className={cn(
                    "flex w-full flex-col gap-0.5 rounded-sm px-2 py-1.5 text-left hover:bg-accent",
                    m === mode && "bg-accent/50"
                  )}
                >
                  <span className="font-medium text-sm">
                    {m === "all" ? t("share.allMembers") : t("share.restricted")}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {m === "all" ? t("share.allMembersHint") : t("share.restrictedHint")}
                  </span>
                </button>
              ))}
            </PopoverContent>
          </Popover>

          {mode === "all" && (
            <Select
              value={allLevel}
              onValueChange={(v) => setAllLevel(v as ShareLevel)}
              disabled={disabled}
            >
              <SelectTrigger className="w-[120px] shrink-0 bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("share.viewer")}</SelectItem>
                <SelectItem value="write">{t("share.editor")}</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>
      </div>

      {/* ── Restricted: People + Roles ─────────────────────────────────── */}
      {mode === "restricted" && (
        <>
          {/* People */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="font-medium text-sm">{t("share.people")}</Label>
              <Popover open={peoplePickerOpen} onOpenChange={setPeoplePickerOpen}>
                <PopoverTrigger asChild>
                  <Button type="button" variant="outline" size="sm" disabled={disabled}>
                    {t("share.addPeople")}
                    <ChevronDown className="ml-1 h-4 w-4 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-0" align="end">
                  <Command>
                    <CommandInput placeholder={t("share.searchPeople")} />
                    <CommandList>
                      <CommandEmpty>{t("share.noPeople")}</CommandEmpty>
                      <CommandGroup>
                        {availableMembers.map((member) => {
                          const displayName = member.user.full_name?.trim() || member.user.email;
                          return (
                            <CommandItem
                              key={member.user.id}
                              value={`${displayName} ${member.user.email}`}
                              onSelect={() => {
                                addUser(member.user.id);
                                setPeoplePickerOpen(false);
                              }}
                              className="cursor-pointer"
                            >
                              <div className="flex flex-col">
                                <span className="truncate text-sm">{displayName}</span>
                                {member.user.full_name?.trim() &&
                                  member.user.full_name.trim() !== member.user.email && (
                                    <span className="truncate text-muted-foreground text-xs">
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

            <div className="space-y-1">
              {/* Owner row (fixed, non-editable) */}
              {ownerId != null && (
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <span className="min-w-0 flex-1 truncate text-sm">{ownerDisplayName}</span>
                  <Badge variant="secondary">{t("share.owner")}</Badge>
                </div>
              )}

              {userGrants.map((grant) => {
                const userId = grant.user_id as number;
                const email = userEmail(userId);
                return (
                  <div key={userId} className="flex items-center gap-2 rounded-md border px-3 py-2">
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm">{userDisplayName(userId)}</span>
                      {email && (
                        <span className="truncate text-muted-foreground text-xs">{email}</span>
                      )}
                    </div>
                    <Select
                      value={grant.level === "write" ? "write" : "read"}
                      onValueChange={(v) => setUserLevel(userId, v as ShareLevel)}
                      disabled={disabled}
                    >
                      <SelectTrigger className="w-[110px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0"
                      onClick={() => removeUser(userId)}
                      disabled={disabled}
                      aria-label={t("share.remove")}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Roles */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="font-medium text-sm">{t("share.roles")}</Label>
              <Popover open={rolePickerOpen} onOpenChange={setRolePickerOpen}>
                <PopoverTrigger asChild>
                  <Button type="button" variant="outline" size="sm" disabled={disabled}>
                    {t("share.addRoles")}
                    <ChevronDown className="ml-1 h-4 w-4 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-0" align="end">
                  <Command>
                    <CommandInput placeholder={t("share.searchRoles")} />
                    <CommandList>
                      <CommandEmpty>{t("share.noRoles")}</CommandEmpty>
                      <CommandGroup>
                        {availableRoles.map((role) => (
                          <CommandItem
                            key={role.id}
                            value={role.display_name}
                            onSelect={() => {
                              addRole(role.id);
                              setRolePickerOpen(false);
                            }}
                            className="cursor-pointer"
                          >
                            <span className="truncate text-sm">{role.display_name}</span>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>

            <div className="space-y-1">
              {/* Full-access roles: locked Editor, non-removable, non-downgradable */}
              {fullAccessRoles.map((role) => (
                <div
                  key={`full-access-${role.id}`}
                  className="flex items-center gap-2 rounded-md border px-3 py-2"
                  title={t("share.fullAccessHint")}
                >
                  <span className="min-w-0 flex-1 truncate text-sm">{role.display_name}</span>
                  <Badge variant="secondary" className="gap-1">
                    <Lock className="h-3 w-3" />
                    {t("share.fullAccess")}
                  </Badge>
                  <span className="w-[110px] shrink-0 px-3 text-muted-foreground text-sm">
                    {t("share.editor")}
                  </span>
                  <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center text-muted-foreground">
                    <Lock className="h-4 w-4" />
                  </span>
                </div>
              ))}

              {editableRoleGrants.map((grant) => {
                const roleId = grant.role_id as number;
                return (
                  <div key={roleId} className="flex items-center gap-2 rounded-md border px-3 py-2">
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {roleDisplayName(roleId)}
                    </span>
                    <Select
                      value={grant.level === "write" ? "write" : "read"}
                      onValueChange={(v) => setRoleLevel(roleId, v as ShareLevel)}
                      disabled={disabled}
                    >
                      <SelectTrigger className="w-[110px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t("share.viewer")}</SelectItem>
                        <SelectItem value="write">{t("share.editor")}</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0"
                      onClick={() => removeRole(roleId)}
                      disabled={disabled}
                      aria-label={t("share.remove")}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
