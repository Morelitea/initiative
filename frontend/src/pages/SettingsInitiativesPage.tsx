import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import type { AxiosError } from "axios";

import { apiClient } from "@/api/client";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { DataTable } from "@/components/ui/data-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useRoleLabels, getRoleLabel } from "@/hooks/useRoleLabels";
import { queryClient } from "@/lib/queryClient";
import { Initiative, InitiativeMember, InitiativeRole, User } from "@/types/api";
import { toast } from "sonner";
import { ArrowUpDown } from "lucide-react";

const INITIATIVES_QUERY_KEY = ["initiatives"];
const NO_USER_VALUE = "none";
const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const SettingsInitiativesPage = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const managedInitiativeIds = useMemo(() => {
    const assignments = user?.initiative_roles ?? [];
    return new Set(
      assignments
        .filter((assignment) => assignment.role === "project_manager")
        .map((assignment) => assignment.initiative_id)
    );
  }, [user]);
  const canManageInitiatives = isAdmin || managedInitiativeIds.size > 0;
  const [initiativeName, setInitiativeName] = useState("");
  const [initiativeDescription, setInitiativeDescription] = useState("");
  const [initiativeColor, setInitiativeColor] = useState(DEFAULT_INITIATIVE_COLOR);
  const { data: roleLabels } = useRoleLabels();
  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: INITIATIVES_QUERY_KEY,
    enabled: canManageInitiatives,
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  const usersQuery = useQuery<User[]>({
    queryKey: ["users"],
    enabled: canManageInitiatives,
    queryFn: async () => {
      const response = await apiClient.get<User[]>("/users/");
      return response.data;
    },
  });

  const createInitiative = useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<Initiative>("/initiatives/", {
        name: initiativeName,
        description: initiativeDescription,
        color: initiativeColor,
      });
      return response.data;
    },
    onSuccess: () => {
      setInitiativeName("");
      setInitiativeDescription("");
      setInitiativeColor(DEFAULT_INITIATIVE_COLOR);
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
  });

  const handleCreateInitiative = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!initiativeName.trim()) {
      return;
    }
    createInitiative.mutate();
  };

  if (!canManageInitiatives) {
    return (
      <p className="text-muted-foreground text-sm">
        You need {projectManagerLabel} permissions to manage initiatives.
      </p>
    );
  }

  if (initiativesQuery.isLoading || usersQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">Loading initiatives…</p>;
  }

  if (
    initiativesQuery.isError ||
    usersQuery.isError ||
    !initiativesQuery.data ||
    !usersQuery.data
  ) {
    return <p className="text-destructive text-sm">Unable to load initiatives.</p>;
  }

  return (
    <div className="space-y-6">
      {isAdmin ? (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle>Create initiative</CardTitle>
            <CardDescription>
              Organize projects and members under a shared initiative.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleCreateInitiative}>
              <Input
                placeholder="Initiative name"
                value={initiativeName}
                onChange={(event) => setInitiativeName(event.target.value)}
                required
              />
              <Textarea
                placeholder="Description (supports Markdown)"
                value={initiativeDescription}
                onChange={(event) => setInitiativeDescription(event.target.value)}
                rows={3}
              />
              <div className="space-y-2">
                <Label htmlFor="initiative-color">Color</Label>
                <ColorPickerPopover
                  id="initiative-color"
                  value={initiativeColor}
                  onChange={setInitiativeColor}
                  triggerLabel="Adjust"
                />
                <p className="text-muted-foreground text-xs">
                  This color highlights projects tied to the initiative.
                </p>
              </div>
              <Button type="submit" disabled={createInitiative.isPending}>
                {createInitiative.isPending ? "Creating…" : "Create initiative"}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {initiativesQuery.data.length === 0 ? (
        <p className="text-muted-foreground text-sm">No initiatives yet.</p>
      ) : (
        initiativesQuery.data.map((initiative) => (
          <InitiativeCard
            key={initiative.id}
            initiative={initiative}
            usersQuery={usersQuery}
            initiativesQuery={initiativesQuery}
            isAdmin={isAdmin}
            managedInitiativeIds={managedInitiativeIds}
            memberLabel={memberLabel}
            projectManagerLabel={projectManagerLabel}
          />
        ))
      )}
    </div>
  );
};

interface InitiativeCardProps {
  initiative: Initiative;
  usersQuery: ReturnType<typeof useQuery<User[]>>;
  initiativesQuery: ReturnType<typeof useQuery<Initiative[]>>;
  isAdmin: boolean;
  managedInitiativeIds: Set<number>;
  memberLabel: string;
  projectManagerLabel: string;
}

const InitiativeCard = ({
  initiative,
  usersQuery,
  initiativesQuery,
  isAdmin,
  managedInitiativeIds,
  memberLabel,
  projectManagerLabel,
}: InitiativeCardProps) => {
  const [selectedUsers, setSelectedUsers] = useState<Record<number, string>>({});
  const [initiativeColorDrafts, setInitiativeColorDrafts] = useState<Record<number, string>>({});
  const canEditMembers = isAdmin || managedInitiativeIds.has(initiative.id);

  useEffect(() => {
    if (initiativesQuery.data) {
      setSelectedUsers((prev) => {
        const next = { ...prev };
        for (const initiative of initiativesQuery.data) {
          if (!(initiative.id in next)) {
            next[initiative.id] = NO_USER_VALUE;
          }
        }
        return next;
      });
    }
  }, [initiativesQuery.data]);

  type InitiativeUpdatePayload = {
    name?: string;
    description?: string;
    color?: string | null;
  };

  const updateInitiative = useMutation({
    mutationFn: async ({
      initiativeId,
      data,
    }: {
      initiativeId: number;
      data: InitiativeUpdatePayload;
    }) => {
      const response = await apiClient.patch<Initiative>(`/initiatives/${initiativeId}`, data);
      return response.data;
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
      setInitiativeColorDrafts((prev) => {
        const next = { ...prev };
        if (variables?.initiativeId in next) {
          delete next[variables.initiativeId];
        }
        return next;
      });
    },
  });

  const deleteInitiative = useMutation({
    mutationFn: async (initiativeId: number) => {
      await apiClient.delete(`/initiatives/${initiativeId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
  });

  const addInitiativeMember = useMutation({
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      const response = await apiClient.post<Initiative>(`/initiatives/${initiativeId}/members`, {
        user_id: userId,
      });
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
  });

  const removeInitiativeMember = useMutation({
    mutationFn: async ({ initiativeId, userId }: { initiativeId: number; userId: number }) => {
      const response = await apiClient.delete<Initiative>(
        `/initiatives/${initiativeId}/members/${userId}`
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
    onError: (error) => {
      const axiosError = error as AxiosError<{ detail?: string }>;
      const detailMessage = axiosError.response?.data?.detail;
      toast.error(detailMessage ?? `Unable to remove initiative ${memberLabel}.`);
    },
  });

  const updateInitiativeMemberRole = useMutation({
    mutationFn: async ({
      initiativeId,
      userId,
      role,
    }: {
      initiativeId: number;
      userId: number;
      role: InitiativeRole;
    }) => {
      const response = await apiClient.patch<Initiative>(
        `/initiatives/${initiativeId}/members/${userId}`,
        { role }
      );
      return response.data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: INITIATIVES_QUERY_KEY });
    },
  });

  const handleInitiativeFieldUpdate = (
    initiativeId: number,
    field: "name" | "description",
    currentValue: string
  ) => {
    const nextValue = window.prompt(`Update initiative ${field}`, currentValue) ?? undefined;
    if (nextValue === undefined || !nextValue.trim()) {
      return;
    }
    updateInitiative.mutate({ initiativeId, data: { [field]: nextValue } });
  };

  const handleInitiativeColorChange = (initiativeId: number, value: string) => {
    updateInitiative.mutate({ initiativeId, data: { color: value } });
  };

  const handleInitiativeColorSave = (initiativeId: number, fallback: string) => {
    const draft = initiativeColorDrafts[initiativeId] ?? fallback;
    handleInitiativeColorChange(initiativeId, draft);
  };

  const handleDeleteInitiative = (initiativeId: number, name: string) => {
    const confirmation = window.prompt(
      `Deleting initiative "${name}" will permanently delete all of its projects and tasks.\n\nType "delete" to confirm.`
    );
    if (!confirmation || confirmation.trim().toLowerCase() !== "delete") {
      return;
    }
    deleteInitiative.mutate(initiativeId);
  };

  const handleAddMember = (initiativeId: number) => {
    const value = selectedUsers[initiativeId];
    if (!value || value === NO_USER_VALUE) {
      return;
    }
    addInitiativeMember.mutate({ initiativeId, userId: Number(value) });
    setSelectedUsers((prev) => ({ ...prev, [initiativeId]: NO_USER_VALUE }));
  };

  const handleRemoveMember = (initiativeId: number, userId: number, email: string) => {
    if (!window.confirm(`Remove ${email} from this initiative?`)) {
      return;
    }
    removeInitiativeMember.mutate({ initiativeId, userId });
  };

  const availableUsers = (initiative: Initiative) =>
    usersQuery.data?.filter(
      (candidate) => !initiative.members.some((member) => member.user.id === candidate.id)
    ) ?? [];

  const userColumns: ColumnDef<InitiativeMember>[] = [
    {
      id: "user",
      header: memberLabel,
      cell: ({ row }) => {
        const initiativeMember = row.original;
        const displayName = initiativeMember.user.full_name?.trim() || "—";
        return (
          <div>
            <p className="font-medium">{displayName}</p>
          </div>
        );
      },
    },
    {
      id: "email",
      accessorKey: "user.email",
      header: ({ column }) => {
        return (
          <div className="flex items-center gap-2">
            Email
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              <ArrowUpDown className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        );
      },
      cell: ({ row }) => {
        const initiativeMember = row.original;
        return <p className="text-muted-foreground text-sm">{initiativeMember.user.email}</p>;
      },
    },
    {
      accessorKey: "role",
      header: "Role",
      cell: ({ row }) => {
        const initiativeMember = row.original;
        return (
          <Select
            value={initiativeMember.role}
            onValueChange={(value) =>
              updateInitiativeMemberRole.mutate({
                initiativeId: initiative.id,
                userId: initiativeMember.user.id,
                role: value as InitiativeRole,
              })
            }
            disabled={!canEditMembers || updateInitiativeMemberRole.isPending}
          >
            <SelectTrigger className="min-w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="project_manager">{projectManagerLabel}</SelectItem>
              <SelectItem value="member">{memberLabel}</SelectItem>
            </SelectContent>
          </Select>
        );
      },
    },
    {
      id: "actions",
      header: "Actions",
      cell: ({ row }) => {
        const initiativeMember = row.original;
        return (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                handleRemoveMember(
                  initiative.id,
                  initiativeMember.user.id,
                  initiativeMember.user.email ?? initiativeMember.user.full_name ?? memberLabel
                )
              }
              disabled={!canEditMembers || removeInitiativeMember.isPending}
            >
              Remove
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <Card className="shadow-sm">
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{initiative.name}</CardTitle>
          {initiative.description ? (
            <Markdown content={initiative.description} className="text-sm" />
          ) : (
            <CardDescription>No description yet.</CardDescription>
          )}
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="w-full max-w-[220px] space-y-2">
            <Label htmlFor={`initiative-color-${initiative.id}`} className="text-xs">
              Color
            </Label>
            <ColorPickerPopover
              id={`initiative-color-${initiative.id}`}
              value={
                initiativeColorDrafts[initiative.id] ?? initiative.color ?? DEFAULT_INITIATIVE_COLOR
              }
              onChange={(nextColor) =>
                setInitiativeColorDrafts((prev) => ({ ...prev, [initiative.id]: nextColor }))
              }
              triggerLabel="Adjust"
              disabled={!isAdmin || updateInitiative.isPending}
            />
            {(() => {
              if (!isAdmin) {
                return null;
              }
              const currentColor = initiative.color ?? DEFAULT_INITIATIVE_COLOR;
              const draftColor = initiativeColorDrafts[initiative.id];
              const hasPendingDraft = typeof draftColor === "string" && draftColor !== currentColor;
              if (!hasPendingDraft) {
                return null;
              }
              return (
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={() => handleInitiativeColorSave(initiative.id, currentColor)}
                  disabled={updateInitiative.isPending}
                >
                  Save color
                </Button>
              );
            })()}
          </div>
          {isAdmin ? (
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleInitiativeFieldUpdate(initiative.id, "name", initiative.name)}
              >
                Rename
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  handleInitiativeFieldUpdate(
                    initiative.id,
                    "description",
                    initiative.description ?? ""
                  )
                }
              >
                Edit description
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleDeleteInitiative(initiative.id, initiative.name)}
                disabled={initiative.is_default || deleteInitiative.isPending}
                title={
                  initiative.is_default ? "The default initiative cannot be deleted." : undefined
                }
              >
                Delete
              </Button>
            </div>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          {initiative.members.length === 0 ? (
            <p className="text-s text-muted-foreground">No {memberLabel} assigned yet.</p>
          ) : (
            <DataTable
              columns={userColumns}
              data={initiative.members}
              enableFilterInput
              filterInputColumnKey="email"
              filterInputPlaceholder="Filter by email..."
              enableResetSorting
            />
          )}
        </div>
        {canEditMembers ? (
          <div className="flex items-end gap-2">
            <SearchableCombobox
              value={selectedUsers[initiative.id] ?? NO_USER_VALUE}
              onValueChange={(value) =>
                setSelectedUsers((prev) => ({ ...prev, [initiative.id]: value }))
              }
              placeholder={`Select ${memberLabel}`}
              items={availableUsers(initiative).map((candidate) => ({
                value: String(candidate.id),
                label: candidate.full_name ?? candidate.email,
              }))}
            />
            <Button
              type="button"
              variant="outline"
              onClick={() => handleAddMember(initiative.id)}
              disabled={addInitiativeMember.isPending}
            >
              Add {memberLabel}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
};
