import { useQuery } from "@tanstack/react-query";

import {
  getRoleLabelsApiV1SettingsRolesGet,
  getGetRoleLabelsApiV1SettingsRolesGetQueryKey,
} from "@/api/generated/settings/settings";
import type { RoleLabels } from "../types/api";

export const DEFAULT_ROLE_LABELS: RoleLabels = {
  admin: "Admin",
  project_manager: "Project manager",
  member: "Member",
};

export const ROLE_LABELS_QUERY_KEY = getGetRoleLabelsApiV1SettingsRolesGetQueryKey();

export const useRoleLabels = () =>
  useQuery({
    queryKey: ROLE_LABELS_QUERY_KEY,
    queryFn: () => getRoleLabelsApiV1SettingsRolesGet() as unknown as Promise<RoleLabels>,
    placeholderData: DEFAULT_ROLE_LABELS,
    staleTime: Infinity,
  });

type RoleKey = keyof RoleLabels;

export const getRoleLabel = (role: RoleKey, labels?: RoleLabels) =>
  labels?.[role] ?? DEFAULT_ROLE_LABELS[role];
