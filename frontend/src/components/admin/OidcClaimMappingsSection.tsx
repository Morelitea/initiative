import { FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiClient } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface OIDCClaimMapping {
  id: number;
  claim_value: string;
  target_type: "guild" | "initiative";
  guild_id: number;
  guild_role: string;
  initiative_id?: number | null;
  initiative_role_id?: number | null;
  guild_name?: string | null;
  initiative_name?: string | null;
  initiative_role_name?: string | null;
}

interface OIDCMappingsData {
  claim_path: string | null;
  mappings: OIDCClaimMapping[];
}

interface OptionItem {
  id: number;
  name: string;
}

interface InitiativeOption extends OptionItem {
  guild_id: number;
}

interface RoleOption extends OptionItem {
  initiative_id: number;
}

interface MappingOptions {
  guilds: OptionItem[];
  initiatives: InitiativeOption[];
  initiative_roles: RoleOption[];
}

const QUERY_KEY = ["settings", "oidc-mappings"];

export const OidcClaimMappingsSection = () => {
  const { t } = useTranslation("settings");
  const queryClient = useQueryClient();

  const [claimPath, setClaimPath] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState({
    claim_value: "",
    target_type: "guild" as "guild" | "initiative",
    guild_id: "",
    guild_role: "member",
    initiative_id: "",
    initiative_role_id: "",
  });

  const mappingsQuery = useQuery<OIDCMappingsData>({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      const resp = await apiClient.get<OIDCMappingsData>("/settings/oidc-mappings");
      return resp.data;
    },
  });

  const optionsQuery = useQuery<MappingOptions>({
    queryKey: [...QUERY_KEY, "options"],
    queryFn: async () => {
      const resp = await apiClient.get<MappingOptions>("/settings/oidc-mappings/options");
      return resp.data;
    },
  });

  useEffect(() => {
    if (mappingsQuery.data) {
      setClaimPath(mappingsQuery.data.claim_path ?? "");
    }
  }, [mappingsQuery.data]);

  const updateClaimPath = useMutation({
    mutationFn: async (path: string | null) => {
      await apiClient.put("/settings/oidc-mappings/claim-path", { claim_path: path || null });
    },
    onSuccess: () => {
      toast.success(t("auth.claimPathSuccess"));
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: () => toast.error(t("auth.claimPathError")),
  });

  const createMapping = useMutation({
    mutationFn: async (data: Record<string, unknown>) => {
      const resp = await apiClient.post<OIDCClaimMapping>("/settings/oidc-mappings", data);
      return resp.data;
    },
    onSuccess: () => {
      toast.success(t("auth.mappingCreateSuccess"));
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      resetForm();
    },
    onError: () => toast.error(t("auth.mappingCreateError")),
  });

  const updateMapping = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: Record<string, unknown> }) => {
      const resp = await apiClient.put<OIDCClaimMapping>(`/settings/oidc-mappings/${id}`, data);
      return resp.data;
    },
    onSuccess: () => {
      toast.success(t("auth.mappingUpdateSuccess"));
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      resetForm();
    },
    onError: () => toast.error(t("auth.mappingUpdateError")),
  });

  const deleteMapping = useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/settings/oidc-mappings/${id}`);
    },
    onSuccess: () => {
      toast.success(t("auth.mappingDeleteSuccess"));
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: () => toast.error(t("auth.mappingDeleteError")),
  });

  const filteredInitiatives = useMemo(() => {
    if (!optionsQuery.data || !form.guild_id) return [];
    return optionsQuery.data.initiatives.filter((i) => i.guild_id === Number(form.guild_id));
  }, [optionsQuery.data, form.guild_id]);

  const filteredRoles = useMemo(() => {
    if (!optionsQuery.data || !form.initiative_id) return [];
    return optionsQuery.data.initiative_roles.filter(
      (r) => r.initiative_id === Number(form.initiative_id)
    );
  }, [optionsQuery.data, form.initiative_id]);

  const resetForm = () => {
    setFormOpen(false);
    setEditingId(null);
    setForm({
      claim_value: "",
      target_type: "guild",
      guild_id: "",
      guild_role: "member",
      initiative_id: "",
      initiative_role_id: "",
    });
  };

  const startEdit = (mapping: OIDCClaimMapping) => {
    setEditingId(mapping.id);
    setFormOpen(true);
    setForm({
      claim_value: mapping.claim_value,
      target_type: mapping.target_type,
      guild_id: String(mapping.guild_id),
      guild_role: mapping.guild_role,
      initiative_id: mapping.initiative_id ? String(mapping.initiative_id) : "",
      initiative_role_id: mapping.initiative_role_id ? String(mapping.initiative_role_id) : "",
    });
  };

  const handleClaimPathSubmit = (e: FormEvent) => {
    e.preventDefault();
    updateClaimPath.mutate(claimPath.trim() || null);
  };

  const handleMappingSubmit = (e: FormEvent) => {
    e.preventDefault();
    const payload: Record<string, unknown> = {
      claim_value: form.claim_value.trim(),
      target_type: form.target_type,
      guild_id: Number(form.guild_id),
      guild_role: form.guild_role,
    };
    if (form.target_type === "initiative") {
      payload.initiative_id = Number(form.initiative_id);
      payload.initiative_role_id = Number(form.initiative_role_id);
    }
    if (editingId) {
      updateMapping.mutate({ id: editingId, data: payload });
    } else {
      createMapping.mutate(payload);
    }
  };

  if (mappingsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("auth.loadingOidcMappings")}</p>;
  }

  if (mappingsQuery.isError || !mappingsQuery.data) {
    return <p className="text-destructive text-sm">{t("auth.oidcMappingsLoadError")}</p>;
  }

  const isSaving = createMapping.isPending || updateMapping.isPending;

  return (
    <>
      {/* Claim Path */}
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("auth.claimPathCardTitle")}</CardTitle>
          <CardDescription>
            {t("auth.claimPathCardDescription")} Keycloak:{" "}
            <code className="bg-muted rounded px-1">realm_access.roles</code>, Azure AD:{" "}
            <code className="bg-muted rounded px-1">groups</code>, Okta:{" "}
            <code className="bg-muted rounded px-1">groups</code>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleClaimPathSubmit} className="flex items-end gap-3">
            <div className="flex-1 space-y-2">
              <Label htmlFor="claim-path">{t("auth.claimPathLabel")}</Label>
              <Input
                id="claim-path"
                value={claimPath}
                onChange={(e) => setClaimPath(e.target.value)}
                placeholder={t("auth.claimPathPlaceholder")}
              />
            </div>
            <Button type="submit" disabled={updateClaimPath.isPending}>
              {updateClaimPath.isPending ? t("auth.claimPathSaving") : t("auth.claimPathSave")}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Mapping Rules */}
      <Card className="shadow-sm">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>{t("auth.rulesTitle")}</CardTitle>
            <CardDescription>{t("auth.rulesDescription")}</CardDescription>
          </div>
          {!formOpen && (
            <Button size="sm" onClick={() => setFormOpen(true)}>
              {t("auth.addRule")}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          {formOpen && (
            <div className="bg-muted/40 rounded-md border p-4">
              <form onSubmit={handleMappingSubmit} className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label>{t("auth.mappingClaimValue")}</Label>
                    <Input
                      value={form.claim_value}
                      onChange={(e) => setForm((p) => ({ ...p, claim_value: e.target.value }))}
                      placeholder={t("auth.mappingClaimValuePlaceholder")}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>{t("auth.mappingTargetType")}</Label>
                    <Select
                      value={form.target_type}
                      onValueChange={(v) =>
                        setForm((p) => ({
                          ...p,
                          target_type: v as "guild" | "initiative",
                          initiative_id: "",
                          initiative_role_id: "",
                        }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="guild">{t("auth.mappingTargetTypeGuild")}</SelectItem>
                        <SelectItem value="initiative">
                          {t("auth.mappingTargetTypeInitiative")}
                        </SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>{t("auth.mappingGuild")}</Label>
                    <Select
                      value={form.guild_id}
                      onValueChange={(v) =>
                        setForm((p) => ({
                          ...p,
                          guild_id: v,
                          initiative_id: "",
                          initiative_role_id: "",
                        }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder={t("auth.mappingGuildPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        {optionsQuery.data?.guilds.map((g) => (
                          <SelectItem key={g.id} value={String(g.id)}>
                            {g.name} <span className="text-muted-foreground">#{g.id}</span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>{t("auth.mappingGuildRole")}</Label>
                    <Select
                      value={form.guild_role}
                      onValueChange={(v) => setForm((p) => ({ ...p, guild_role: v }))}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="member">{t("auth.mappingRoleMember")}</SelectItem>
                        <SelectItem value="admin">{t("auth.mappingRoleAdmin")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  {form.target_type === "initiative" && (
                    <>
                      <div className="space-y-2">
                        <Label>{t("auth.mappingInitiative")}</Label>
                        <Select
                          value={form.initiative_id}
                          onValueChange={(v) =>
                            setForm((p) => ({ ...p, initiative_id: v, initiative_role_id: "" }))
                          }
                          disabled={!form.guild_id}
                        >
                          <SelectTrigger>
                            <SelectValue
                              placeholder={
                                form.guild_id
                                  ? t("auth.mappingInitiativePlaceholder")
                                  : t("auth.mappingSelectGuildFirst")
                              }
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {filteredInitiatives.map((i) => (
                              <SelectItem key={i.id} value={String(i.id)}>
                                {i.name} <span className="text-muted-foreground">#{i.id}</span>
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>{t("auth.mappingInitiativeRole")}</Label>
                        <Select
                          value={form.initiative_role_id}
                          onValueChange={(v) => setForm((p) => ({ ...p, initiative_role_id: v }))}
                          disabled={!form.initiative_id}
                        >
                          <SelectTrigger>
                            <SelectValue
                              placeholder={
                                form.initiative_id
                                  ? t("auth.mappingInitiativeRolePlaceholder")
                                  : t("auth.mappingSelectInitiativeFirst")
                              }
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {filteredRoles.map((r) => (
                              <SelectItem key={r.id} value={String(r.id)}>
                                {r.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}
                </div>
                <div className="flex gap-2">
                  <Button type="submit" size="sm" disabled={isSaving}>
                    {isSaving
                      ? t("auth.mappingSaving")
                      : editingId
                        ? t("auth.mappingUpdate")
                        : t("auth.mappingAdd")}
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={resetForm}>
                    {t("auth.mappingCancel")}
                  </Button>
                </div>
              </form>
            </div>
          )}

          {mappingsQuery.data.mappings.length === 0 ? (
            <p className="text-muted-foreground py-4 text-center text-sm">{t("auth.noRules")}</p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("auth.mappingColumnClaim")}</TableHead>
                    <TableHead>{t("auth.mappingColumnType")}</TableHead>
                    <TableHead>{t("auth.mappingColumnGuild")}</TableHead>
                    <TableHead>{t("auth.mappingColumnGuildRole")}</TableHead>
                    <TableHead>{t("auth.mappingColumnInitiative")}</TableHead>
                    <TableHead>{t("auth.mappingColumnInitiativeRole")}</TableHead>
                    <TableHead className="text-right">{t("auth.mappingColumnActions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mappingsQuery.data.mappings.map((m) => (
                    <TableRow key={m.id}>
                      <TableCell className="font-mono text-sm">{m.claim_value}</TableCell>
                      <TableCell className="capitalize">{m.target_type}</TableCell>
                      <TableCell>
                        {m.guild_name ?? m.guild_id}{" "}
                        <span className="text-muted-foreground">#{m.guild_id}</span>
                      </TableCell>
                      <TableCell className="capitalize">{m.guild_role}</TableCell>
                      <TableCell>
                        {m.initiative_name ? (
                          <>
                            {m.initiative_name}{" "}
                            <span className="text-muted-foreground">#{m.initiative_id}</span>
                          </>
                        ) : m.initiative_id ? (
                          `#${m.initiative_id}`
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>
                        {m.initiative_role_name ??
                          (m.initiative_role_id ? m.initiative_role_id : "-")}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => startEdit(m)}>
                            {t("auth.mappingEdit")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive"
                            onClick={() => deleteMapping.mutate(m.id)}
                            disabled={deleteMapping.isPending}
                          >
                            {t("auth.mappingDelete")}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
};
