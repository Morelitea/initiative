import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/api/client";
import type { RoleLabels } from "../types/api";

export const DEFAULT_ROLE_LABELS: RoleLabels = {
  admin: "Admin",
  project_manager: "Project manager",
  member: "Member",
};

export const ROLE_LABELS_QUERY_KEY = ["settings", "role-labels"];

export const useRoleLabels = () =>
  useQuery({
    queryKey: ROLE_LABELS_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<RoleLabels>("/settings/roles");
      return response.data;
    },
    placeholderData: DEFAULT_ROLE_LABELS,
    staleTime: Infinity,
  });

type RoleKey = keyof RoleLabels;

export const getRoleLabel = (role: RoleKey, labels?: RoleLabels) =>
  labels?.[role] ?? DEFAULT_ROLE_LABELS[role];
