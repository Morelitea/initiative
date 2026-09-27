import { Blocks, ChevronDown, Loader2, Lock, Users, X } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { OwnerAppSummary, ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { type MemberLike, useSeenMembers } from "@/components/members/MemberSearchSelect";
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
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuildApps } from "@/hooks/useGuildApps";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import { useInitiative } from "@/hooks/useInitiatives";
import { type MemberSearchScope, useMemberSearch } from "@/hooks/useUsers";
import { resolveArtworkUrl } from "@/lib/uploadUrl";
import { getUserDisplayName, getUserHandle } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

// ─── Props ───────────────────────────────────────────────────────────────────

export interface ShareControlProps {
  /** The initiative whose members and roles can be named, or `null` for a
   *  guild-level resource — where the people who can be named are the guild's
   *  members, and no initiative is read at all.
   *
   *  `null` selects the **guild view** of this control. The two views are not
   *  cosmetic: an initiative has roles and a guild does not, so the guild view
   *  has no Roles section at all rather than an empty one. See the note above
   *  {@link ShareControl}. */
  initiativeId: number | null;
  /** Full grant list for the resource (may include the owner-level grant). */
  grants: ResourceGrantSchema[];
  /** Called with the full NON-owner grant list to persist. */
  onChange: (grants: ResourceGrantSchema[]) => void;
  /** When given, a fixed, non-editable "Owner" row is shown. Omit in create. */
  ownerId?: number | null;
  /** The installed app that owns the resource, as its read model names it.
   *  An app owner's row is shown whenever the grants hold one; this supplies
   *  its name and picture without looking the app up. */
  ownerApp?: OwnerAppSummary | null;
  /** Viewer can't manage, or a save is in flight. */
  disabled?: boolean;
}

type ShareLevel = "read" | "write";

const GUILD_SCOPE: MemberSearchScope = { type: "guild" };

/** An app's picture, small, or the generic app mark when it has none. */
const AppMark = ({ avatarUrl }: { avatarUrl: string | null | undefined }) =>
  avatarUrl ? (
    <img
      src={resolveArtworkUrl(avatarUrl) ?? undefined}
      alt=""
      aria-hidden
      className="h-5 w-5 shrink-0 rounded-sm object-cover"
      loading="lazy"
    />
  ) : (
    <Blocks className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
  );

// ─── Component ───────────────────────────────────────────────────────────────

/**
 * Who can read and write one resource — in one of two views.
 *
 * **Initiative view** (`initiativeId` given) shares within an initiative: its
 * members, and its roles, and "everyone in the initiative".
 *
 * **Guild view** (`initiativeId` null) shares a guild-level resource, and it is
 * a narrower thing rather than the same thing with different words. A guild has
 * members, so people can be named. A guild has no *roles* — the roles this
 * control grants to are an initiative's, and there is no initiative here — so
 * the guild view has no Roles section, rather than one with an empty picker
 * behind it offering a grant the server would drop on the way in.
 *
 * "Everyone" survives both views because both have one: at guild scope the
 * all-members grant reads as every member of the guild, which is how a guild
 * calendar arrives shared with the guild.
 *
 * An installed app may be the owner, or a grantee the community's seat named.
 * Both are shown by the app's name and never edited here: an app's grant is
 * the seat's decision, and the server keeps it whatever this list sends.
 */
export const ShareControl = ({
  initiativeId,
  grants,
  onChange,
  ownerId,
  ownerApp,
  disabled = false,
}: ShareControlProps) => {
  const { t } = useTranslation(["access", "common"]);

  // Guild-level resource: there is no initiative to read, so the people come
  // from the guild. Roles stay empty — a guild role is not an initiative role,
  // and granting to one is not something this build does.
  const guildScoped = initiativeId == null;
  const { data: roles = [] } = useInitiativeRoles(initiativeId);
  const { data: initiative } = useInitiative(initiativeId);

  // ── Derived grant buckets ────────────────────────────────────────────────

  const allMembersGrant = useMemo(() => grants.find((g) => g.all_initiative_members), [grants]);
  const mode: "all" | "restricted" = allMembersGrant ? "all" : "restricted";

  const userGrants = useMemo(
    () => grants.filter((g) => g.user_id != null && g.level !== "owner"),
    [grants]
  );
  // A role grant cannot mean anything on a guild-level resource: the roles are
  // an initiative's, and the server drops such a grant rather than storing one
  // that names nothing. Emptied here so the guild view never carries one
  // through an edit either — what it shows is what gets saved.
  const roleGrants = useMemo(
    () => (guildScoped ? [] : grants.filter((g) => g.role_id != null)),
    [guildScoped, grants]
  );

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

  // ── People: an initiative's roster, or the guild's searched ─────────────

  const [peoplePickerOpen, setPeoplePickerOpen] = useState(false);
  const [peopleQuery, setPeopleQuery] = useState("");
  const debouncedPeopleQuery = useDebouncedValue(peopleQuery, 250);

  // A guild's roster is too large to hold: the picker asks the server for the
  // people matching what was typed, and the people already named here (owner,
  // grantees) are looked up by id.
  const guildSearch = useMemberSearch(GUILD_SCOPE, {
    search: debouncedPeopleQuery,
    enabled: guildScoped && peoplePickerOpen,
  });
  const guildResults = useMemo(() => guildSearch.data?.items ?? [], [guildSearch.data]);
  const namedGuildUserIds = useMemo(
    () =>
      guildScoped
        ? [...(ownerId != null ? [ownerId] : []), ...userGrants.map((g) => g.user_id as number)]
        : [],
    [guildScoped, ownerId, userGrants]
  );
  const seenGuildMembers = useSeenMembers(GUILD_SCOPE, namedGuildUserIds, undefined, guildResults);

  const findMember = useCallback(
    (userId: number): MemberLike | undefined =>
      guildScoped
        ? seenGuildMembers.get(userId)
        : initiative?.members.find((m) => m.user.id === userId)?.user,
    [guildScoped, seenGuildMembers, initiative?.members]
  );

  // ── Apps: the owning install, and the ones the seat granted ──────────────

  const ownerAppId = useMemo(
    () => grants.find((g) => g.level === "owner" && g.app_install_id != null)?.app_install_id,
    [grants]
  );
  const appGrants = useMemo(
    () => grants.filter((g) => g.app_install_id != null && g.level !== "owner"),
    [grants]
  );
  // The apps list is only read when a grant names an app the read model did
  // not already describe.
  const needsAppNames = appGrants.length > 0 || (ownerAppId != null && ownerApp?.id !== ownerAppId);
  const { data: guildApps } = useGuildApps({ enabled: needsAppNames });

  const appSummary = useCallback(
    (appId: number): { name: string; avatarUrl: string | null } => {
      if (ownerApp?.id === appId) return { name: ownerApp.name, avatarUrl: ownerApp.avatar_url };
      const app = guildApps?.items.find((one) => one.id === appId);
      return app
        ? { name: app.name, avatarUrl: app.avatar_url }
        : { name: t("share.appFallback", { id: appId }), avatarUrl: null };
    },
    [ownerApp, guildApps, t]
  );
  const owningApp = ownerId == null && ownerAppId != null ? appSummary(ownerAppId) : null;

  // ── Lookup helpers ───────────────────────────────────────────────────────

  const userDisplayName = useCallback(
    (userId: number): string => {
      const member = findMember(userId);
      return member ? getUserDisplayName(member) : `User ${userId}`;
    },
    [findMember]
  );

  // The handle, as the line under a name — what tells two people with the same
  // name apart. Nothing to show when the name IS the handle.
  const userHandle = useCallback(
    (userId: number): string | null => {
      const member = findMember(userId);
      if (!member?.full_name?.trim()) return null;
      return getUserHandle(member) || null;
    },
    [findMember]
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
    () =>
      (guildScoped
        ? guildResults
        : (initiative?.members ?? []).map((member) => member.user)
      ).filter((user) => user.id !== ownerId && !grantedUserIds.has(user.id)),
    [guildScoped, guildResults, initiative?.members, ownerId, grantedUserIds]
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
  const [rolePickerOpen, setRolePickerOpen] = useState(false);

  const handlePeoplePickerOpenChange = (open: boolean) => {
    setPeoplePickerOpen(open);
    if (!open) setPeopleQuery("");
  };

  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="min-w-0 space-y-4">
      {/* ── Share ─────────────────────────────────────────────────────── */}
      <div className="space-y-2">
        <Label className="font-medium text-sm">{t("share.title")}</Label>
        <div
          className={cn(
            // Wraps rather than overflows: the level select is a fixed 120px
            // and the labels are translated, so on a narrow dialog the two
            // cannot always share a line. Wrapping puts the select underneath;
            // not wrapping put it off the side of the screen.
            "flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2.5",
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
                className="flex min-w-[8rem] flex-1 flex-col text-left focus:outline-none disabled:cursor-not-allowed"
              >
                <span className="flex items-center gap-1">
                  <span className="truncate font-medium text-sm">
                    {mode === "all"
                      ? t(guildScoped ? "share.allGuildMembers" : "share.allMembers")
                      : t("share.restricted")}
                  </span>
                  <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
                </span>
                <span className="truncate text-muted-foreground text-xs">
                  {mode === "all"
                    ? t(guildScoped ? "share.allGuildMembersHint" : "share.allMembersHint")
                    : t(guildScoped ? "share.restrictedGuildHint" : "share.restrictedHint")}
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
                    {m === "all"
                      ? t(guildScoped ? "share.allGuildMembers" : "share.allMembers")
                      : t("share.restricted")}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {m === "all"
                      ? t(guildScoped ? "share.allGuildMembersHint" : "share.allMembersHint")
                      : t(guildScoped ? "share.restrictedGuildHint" : "share.restrictedHint")}
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
              <Popover open={peoplePickerOpen} onOpenChange={handlePeoplePickerOpenChange}>
                <PopoverTrigger asChild>
                  <Button type="button" variant="outline" size="sm" disabled={disabled}>
                    {t("share.addPeople")}
                    <ChevronDown className="h-4 w-4 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-0" align="end">
                  {/* A guild's people are matched on the server; an initiative's
                      roster is already here and filters as you type. */}
                  <Command shouldFilter={!guildScoped}>
                    <CommandInput
                      placeholder={t("share.searchPeople")}
                      value={peopleQuery}
                      onValueChange={setPeopleQuery}
                    />
                    <CommandList>
                      {guildScoped && guildSearch.isFetching && availableMembers.length === 0 ? (
                        <div className="flex items-center justify-center gap-2 py-6 text-muted-foreground text-sm">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          {t("common:loading")}
                        </div>
                      ) : (
                        <CommandEmpty>{t("share.noPeople")}</CommandEmpty>
                      )}
                      <CommandGroup>
                        {availableMembers.map((member) => {
                          const displayName = getUserDisplayName(member);
                          return (
                            <CommandItem
                              key={member.id}
                              value={`${displayName} ${getUserHandle(member)}`}
                              onSelect={() => {
                                addUser(member.id);
                                handlePeoplePickerOpenChange(false);
                              }}
                              className="cursor-pointer"
                            >
                              <div className="flex flex-col">
                                <span className="truncate text-sm">{displayName}</span>
                                {member.full_name?.trim() && (
                                  <span className="truncate text-muted-foreground text-xs">
                                    {getUserHandle(member)}
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
              {owningApp && (
                <div className="flex items-center gap-2 rounded-md border px-3 py-2">
                  <AppMark avatarUrl={owningApp.avatarUrl} />
                  <span className="min-w-0 flex-1 truncate text-sm">{owningApp.name}</span>
                  <Badge variant="outline">{t("share.app")}</Badge>
                  <Badge variant="secondary">{t("share.owner")}</Badge>
                </div>
              )}

              {userGrants.map((grant) => {
                const userId = grant.user_id as number;
                const handle = userHandle(userId);
                return (
                  <div key={userId} className="flex items-center gap-2 rounded-md border px-3 py-2">
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-sm">{userDisplayName(userId)}</span>
                      {handle && (
                        <span className="truncate text-muted-foreground text-xs">{handle}</span>
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

          {/* Roles — an initiative's, so the guild view has none. Absent
              rather than empty: an "Add roles" button over a picker with
              nothing in it offers a grant that names nothing, which the server
              would drop on the way in. */}
          {guildScoped ? null : (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="font-medium text-sm">{t("share.roles")}</Label>
                <Popover open={rolePickerOpen} onOpenChange={setRolePickerOpen}>
                  <PopoverTrigger asChild>
                    <Button type="button" variant="outline" size="sm" disabled={disabled}>
                      {t("share.addRoles")}
                      <ChevronDown className="h-4 w-4 opacity-50" />
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
                    <div
                      key={roleId}
                      className="flex items-center gap-2 rounded-md border px-3 py-2"
                    >
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
          )}
        </>
      )}

      {/* ── Apps the community granted: shown, never edited here ──────── */}
      {appGrants.length > 0 && (
        <div className="space-y-2">
          <Label className="font-medium text-sm">{t("share.apps")}</Label>
          <div className="space-y-1">
            {appGrants.map((grant) => {
              const appId = grant.app_install_id as number;
              const app = appSummary(appId);
              return (
                <div
                  key={`app-${appId}`}
                  className="flex items-center gap-2 rounded-md border px-3 py-2"
                  title={t("share.appGrantHint")}
                >
                  <AppMark avatarUrl={app.avatarUrl} />
                  <span className="min-w-0 flex-1 truncate text-sm">{app.name}</span>
                  <span className="w-[110px] shrink-0 px-3 text-muted-foreground text-sm">
                    {grant.level === "write" ? t("share.editor") : t("share.viewer")}
                  </span>
                  <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center text-muted-foreground">
                    <Lock className="h-4 w-4" />
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
