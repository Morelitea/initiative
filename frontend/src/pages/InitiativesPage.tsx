import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { Markdown } from "../components/Markdown";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { ColorPickerPopover } from "../components/ui/color-picker-popover";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import { useAuth } from "../hooks/useAuth";
import { queryClient } from "../lib/queryClient";
import { Initiative, User } from "../types/api";

const INITIATIVES_QUERY_KEY = ["initiatives"];
const NO_USER_VALUE = "none";
const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativesPage = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [initiativeName, setInitiativeName] = useState("");
  const [initiativeDescription, setInitiativeDescription] = useState("");
  const [initiativeColor, setInitiativeColor] = useState(DEFAULT_INITIATIVE_COLOR);
  const [selectedUsers, setSelectedUsers] = useState<Record<number, string>>({});
  const [initiativeColorDrafts, setInitiativeColorDrafts] = useState<Record<number, string>>({});

  const initiativesQuery = useQuery<Initiative[]>({
    queryKey: INITIATIVES_QUERY_KEY,
    enabled: isAdmin,
    queryFn: async () => {
      const response = await apiClient.get<Initiative[]>("/initiatives/");
      return response.data;
    },
  });

  const usersQuery = useQuery<User[]>({
    queryKey: ["users"],
    enabled: isAdmin,
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
  });

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

  const handleCreateInitiative = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!initiativeName.trim()) {
      return;
    }
    createInitiative.mutate();
  };

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

  if (!isAdmin) {
    return (
      <p className="text-sm text-muted-foreground">
        You need admin permissions to manage initiatives.
      </p>
    );
  }

  if (initiativesQuery.isLoading || usersQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading initiatives…</p>;
  }

  if (
    initiativesQuery.isError ||
    usersQuery.isError ||
    !initiativesQuery.data ||
    !usersQuery.data
  ) {
    return <p className="text-sm text-destructive">Unable to load initiatives.</p>;
  }

  const availableUsers = (initiative: Initiative) =>
    usersQuery.data?.filter(
      (candidate) => !initiative.members.some((member) => member.id === candidate.id)
    ) ?? [];

  return (
    <div className="space-y-6">
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
              <p className="text-xs text-muted-foreground">
                This color highlights projects tied to the initiative.
              </p>
            </div>
            <Button type="submit" disabled={createInitiative.isPending}>
              {createInitiative.isPending ? "Creating…" : "Create initiative"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {initiativesQuery.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No initiatives yet.</p>
      ) : (
        initiativesQuery.data.map((initiative) => (
          <Card key={initiative.id} className="shadow-sm">
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
                      initiativeColorDrafts[initiative.id] ??
                      initiative.color ??
                      DEFAULT_INITIATIVE_COLOR
                    }
                    onChange={(nextColor) =>
                      setInitiativeColorDrafts((prev) => ({ ...prev, [initiative.id]: nextColor }))
                    }
                    triggerLabel="Adjust"
                    disabled={updateInitiative.isPending}
                  />
                  {(() => {
                    const currentColor = initiative.color ?? DEFAULT_INITIATIVE_COLOR;
                    const draftColor = initiativeColorDrafts[initiative.id];
                    const hasPendingDraft =
                      typeof draftColor === "string" && draftColor !== currentColor;
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
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      handleInitiativeFieldUpdate(initiative.id, "name", initiative.name)
                    }
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
                    disabled={deleteInitiative.isPending}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-sm font-medium">Members</p>
                {initiative.members.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No members yet.</p>
                ) : (
                  <ul className="mt-2 space-y-1 text-sm">
                    {initiative.members.map((member) => (
                      <li key={member.id} className="flex items-center justify-between gap-2">
                        <span>{member.full_name ?? member.email}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRemoveMember(initiative.id, member.id, member.email)}
                          disabled={removeInitiativeMember.isPending}
                        >
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="flex items-end gap-2">
                <Select
                  value={selectedUsers[initiative.id] ?? NO_USER_VALUE}
                  onValueChange={(value) =>
                    setSelectedUsers((prev) => ({ ...prev, [initiative.id]: value }))
                  }
                >
                  <SelectTrigger className="w-72">
                    <SelectValue placeholder="Select member" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_USER_VALUE}>Select a user</SelectItem>
                    {availableUsers(initiative).map((candidate) => (
                      <SelectItem key={candidate.id} value={String(candidate.id)}>
                        {candidate.full_name ?? candidate.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => handleAddMember(initiative.id)}
                  disabled={addInitiativeMember.isPending}
                >
                  Add member
                </Button>
              </div>
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
};
