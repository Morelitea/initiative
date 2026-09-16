import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import type {
  InitiativeRoleCreate,
  InitiativeRoleRead,
  InitiativeRoleUpdate,
  MyInitiativePermissions,
  PermissionKey,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesPost,
  deleteInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdDelete,
  getGetMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGetQueryKey,
  getListInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGetQueryKey,
  getMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGet,
  listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet,
  updateInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdPatch,
} from "@/api/generated/initiatives/initiatives";
import { invalidate, q } from "@/api/query-keys";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  DEFAULT_ENABLED_TOOLS,
  TOOLS,
  toolCamelPlural,
  toolCreatePermission,
  toolPascalPlural,
  toolViewPermission,
} from "@/lib/tools";

export const useInitiativeRoles = (initiativeId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<InitiativeRoleRead[]>({
    queryKey: getListInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGetQueryKey(
      guildId,
      initiativeId!
    ),
    queryFn: () =>
      listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet(guildId, initiativeId!),
    enabled: !!initiativeId,
    staleTime: 30 * 1000,
  });
};

export const useMyInitiativePermissions = (initiativeId: number | null) => {
  const guildId = useActiveGuildId();
  return useQuery<MyInitiativePermissions>({
    queryKey:
      getGetMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGetQueryKey(
        guildId,
        initiativeId!
      ),
    queryFn: () =>
      getMyInitiativePermissionsApiV1GGuildIdInitiativesInitiativeIdMyPermissionsGet(
        guildId,
        initiativeId!
      ),
    enabled: !!initiativeId,
    staleTime: 60 * 1000,
  });
};

export const useCreateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async (data: InitiativeRoleCreate) => {
      return createInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesPost(
        guildId,
        initiativeId,
        data
      );
    },
    onSuccess: () => {
      toast.success(t("settings.roleCreated"));
      void invalidate(q.initiativeRoles(initiativeId));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleCreateError"));
    },
  });
};

export const useUpdateRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async ({ roleId, data }: { roleId: number; data: InitiativeRoleUpdate }) => {
      return updateInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdPatch(
        guildId,
        initiativeId,
        roleId,
        data
      );
    },
    onSuccess: () => {
      toast.success(t("settings.roleUpdated"));
      void invalidate(q.initiativeRoles(initiativeId), q.myPermissions(initiativeId));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleUpdateError"));
    },
  });
};

/**
 * Grant one tool's view permission to every role that isn't a manager.
 *
 * The other half of turning a tool on: the master switch makes the initiative
 * offer the tool, this makes the roles able to see it. Manager roles are
 * skipped because they already see everything, and the create permission is
 * left alone — being able to read a board and being able to add to it are
 * separate decisions, and this one only answers the first.
 *
 * Three things this is careful about, because the whole point of the feature
 * is that a tool is never quietly visible to fewer people than was asked for:
 *
 * - **The roster is read here, not passed in.** A cached list that is still
 *   loading or failed to load is an empty list, and granting to nobody must
 *   not report success. Reading it as part of the mutation means a roster that
 *   cannot be fetched fails the grant instead.
 * - **Only the one key is sent.** The endpoint merges the keys it is given, so
 *   resending a whole snapshot could write back a permission somebody else
 *   changed since it was read.
 * - **Every role is attempted.** One role's failure does not skip the rest;
 *   the error is raised after the others have been tried, so a retry has less
 *   to do and the audience line already reflects who really has it.
 */
export const useGrantToolToRoles = (initiativeId: number) => {
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async ({ tool }: { tool: Tool }) => {
      const key = toolViewPermission(tool);
      const roles = await listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet(
        guildId,
        initiativeId
      );
      const needsGrant = roles.filter(
        (role) => !role.is_manager && !(role.permissions[key] ?? false)
      );
      const results = await Promise.allSettled(
        needsGrant.map((role) =>
          updateInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdPatch(
            guildId,
            initiativeId,
            role.id,
            { permissions: { [key]: true } }
          )
        )
      );
      const failed = results.find((r) => r.status === "rejected");
      if (failed) throw failed.reason;
      return needsGrant.length;
    },
    onSettled: () => {
      void invalidate(q.initiativeRoles(initiativeId), q.myPermissions(initiativeId));
    },
  });
};

/**
 * What the ordinary roles may do with a set of tools — the question a brand-new
 * initiative has to answer and cannot answer for itself.
 *
 * The built-in `member` role ships view-only on projects and documents and
 * `create_*` off everywhere (the backend's DEFAULT_PERMISSION_VALUES). So an
 * initiative created with, say, a calendar has that calendar on for its
 * managers and invisible to everybody else — the state `ToolAudience` warns
 * about after the fact. The create wizard asks once, up front, and this applies
 * the answer.
 *
 * "managers" writes nothing, which is that default. Manager roles are skipped
 * because they hold every permission by construction.
 */
export const useGrantToolsToMembers = () => {
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async ({
      initiativeId,
      tools,
      audience,
    }: {
      /** Passed per call, not bound to the hook: the caller is the create
       *  wizard, and the initiative does not exist at the render that set this
       *  mutation up. Closing over an id from state would send the writes to
       *  whatever that state held a render ago — which is nothing. */
      initiativeId: number;
      tools: Tool[];
      audience: "create" | "view" | "managers";
    }) => {
      if (tools.length === 0) return 0;
      // Written for every chosen tool, in all three answers. "Managers only"
      // is a revoke, not a no-op: the built-in member role arrives holding
      // projects and documents, so leaving it alone would answer "managers
      // only" with members who can still see both.
      const permissions: Record<string, boolean> = {};
      for (const tool of tools) {
        permissions[toolViewPermission(tool)] = audience !== "managers";
        permissions[toolCreatePermission(tool)] = audience === "create";
      }
      const roles = await listInitiativeRolesApiV1GGuildIdInitiativesInitiativeIdRolesGet(
        guildId,
        initiativeId
      );
      const ordinary = roles.filter((role) => !role.is_manager);
      const results = await Promise.allSettled(
        ordinary.map((role) =>
          updateInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdPatch(
            guildId,
            initiativeId,
            role.id,
            { permissions }
          )
        )
      );
      const failed = results.find((r) => r.status === "rejected");
      if (failed) throw failed.reason;
      return ordinary.length;
    },
    onSettled: (_data, _error, variables) => {
      void invalidate(
        q.initiativeRoles(variables.initiativeId),
        q.myPermissions(variables.initiativeId)
      );
    },
  });
};

export const useDeleteRole = (initiativeId: number) => {
  const { t } = useTranslation("initiatives");
  const guildId = useActiveGuildId();

  return useMutation({
    mutationFn: async (roleId: number) => {
      await deleteInitiativeRoleApiV1GGuildIdInitiativesInitiativeIdRolesRoleIdDelete(
        guildId,
        initiativeId,
        roleId
      );
    },
    onSuccess: () => {
      toast.success(t("settings.roleDeleted"));
      void invalidate(q.initiativeRoles(initiativeId));
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, "initiatives:settings.roleDeleteError"));
    },
  });
};

// Helper to check if user has a specific permission
export const hasPermission = (
  permissions: MyInitiativePermissions | undefined,
  key: PermissionKey
): boolean => {
  if (!permissions) return false;
  // Managers always have all permissions
  if (permissions.is_manager) return true;
  return permissions.permissions[key] ?? false;
};

// Helper to check if a tool is visible to the user.
// Reads the permission value directly — the backend already accounts for
// initiative-level master switches and manager status, so we must not
// short-circuit on is_manager here.
export const isToolVisible = (
  permissions: MyInitiativePermissions | undefined,
  tool: Tool
): boolean => {
  if (!permissions) return false;
  return permissions.permissions[toolViewPermission(tool)] ?? false;
};

// Helper to check if the user can create a tool's content.
// Same as isToolVisible — reads the backend value directly.
export const canCreateTool = (
  permissions: MyInitiativePermissions | undefined,
  tool: Tool
): boolean => {
  if (!permissions) return false;
  return permissions.permissions[toolCreatePermission(tool)] ?? false;
};

// i18n-based permission label keys (use with t()) — one view/create pair per
// tool, derived: settings.permissions.view{PascalPlural} / create{PascalPlural}.
export const PERMISSION_LABEL_KEYS: Record<PermissionKey, string> = Object.fromEntries(
  TOOLS.flatMap((tool) => [
    [toolViewPermission(tool), `settings.permissions.view${toolPascalPlural(tool)}`],
    [toolCreatePermission(tool), `settings.permissions.create${toolPascalPlural(tool)}`],
  ])
) as Record<PermissionKey, string>;

// All permission keys in display order (view before create, per tool)
export const ALL_PERMISSION_KEYS: PermissionKey[] = TOOLS.flatMap((tool) => [
  toolViewPermission(tool),
  toolCreatePermission(tool),
]);

// Permission groups for card-based layout
export type PermissionGroup = {
  labelKey: string;
  keys: PermissionKey[];
};

const toolPermissionGroup = (tool: Tool): PermissionGroup => ({
  labelKey: `settings.permissionGroups.${toolCamelPlural(tool)}`,
  keys: [toolViewPermission(tool), toolCreatePermission(tool)],
});

// The permissions for the tools an initiative starts with, always visible.
// This is a question of what to put in front of someone editing a role, not of
// what a tool is: every tool is switchable now, and these two are simply the
// ones almost every initiative has.
export const CORE_PERMISSION_GROUPS: PermissionGroup[] = TOOLS.filter((tool) =>
  DEFAULT_ENABLED_TOOLS.has(tool)
).map(toolPermissionGroup);

// The rest, shown in an accordion.
export const ADVANCED_PERMISSION_GROUPS: PermissionGroup[] = TOOLS.filter(
  (tool) => !DEFAULT_ENABLED_TOOLS.has(tool)
).map(toolPermissionGroup);

// All groups combined (for backward compat)
export const PERMISSION_GROUPS: PermissionGroup[] = [
  ...CORE_PERMISSION_GROUPS,
  ...ADVANCED_PERMISSION_GROUPS,
];
