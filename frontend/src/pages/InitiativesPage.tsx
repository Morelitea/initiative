import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearch } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { getListInitiativesApiV1InitiativesGetQueryKey } from "@/api/generated/initiatives/initiatives";
import { useInitiatives, useCreateInitiative } from "@/hooks/useInitiatives";
import { useProjects } from "@/hooks/useProjects";
import { useDocumentsList } from "@/hooks/useDocuments";
import { Markdown } from "@/components/Markdown";
import { PullToRefresh } from "@/components/PullToRefresh";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import { useGuildPath } from "@/lib/guildUrl";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { getRoleLabel, useRoleLabels } from "@/hooks/useRoleLabels";
import type { Initiative } from "@/types/api";

const DEFAULT_INITIATIVE_COLOR = "#6366F1";

export const InitiativesPage = () => {
  const { user } = useAuth();
  const { t } = useTranslation("initiatives");
  const { activeGuild } = useGuilds();
  const { data: roleLabels } = useRoleLabels();
  const gp = useGuildPath();
  const queryClient = useQueryClient();
  const searchParams = useSearch({ strict: false }) as { create?: string };

  const initiativesQueryKey = getListInitiativesApiV1InitiativesGetQueryKey();

  const handleRefresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: initiativesQueryKey });
  }, [queryClient, initiativesQueryKey]);

  const guildAdminLabel = getRoleLabel("admin", roleLabels);
  const projectManagerLabel = getRoleLabel("project_manager", roleLabels);
  const memberLabel = getRoleLabel("member", roleLabels);

  const isGuildAdmin = activeGuild?.role === "admin" || user?.role === "admin";
  const canCreateInitiatives = Boolean(activeGuild && isGuildAdmin);

  const initiativesQuery = useInitiatives({ enabled: Boolean(activeGuild) });

  const projectsQuery = useProjects(undefined, {
    enabled: Boolean(activeGuild),
    staleTime: 30_000,
  });

  const documentsListQuery = useDocumentsList({ page_size: 0 });

  const visibleInitiatives = useMemo(() => {
    if (!user) {
      return [];
    }
    const source = initiativesQuery.data ?? [];
    if (isGuildAdmin) {
      return source.slice().sort((a, b) => a.name.localeCompare(b.name));
    }
    const membershipFiltered = source.filter((initiative) =>
      initiative.members.some((member) => member.user.id === user.id)
    );
    return membershipFiltered.sort((a, b) => a.name.localeCompare(b.name));
  }, [initiativesQuery.data, user, isGuildAdmin]);

  const projectCounts = useMemo(() => {
    const counts = new Map<number, number>();
    const projects = Array.isArray(projectsQuery.data) ? projectsQuery.data : [];
    projects.forEach((project) => {
      counts.set(project.initiative_id, (counts.get(project.initiative_id) ?? 0) + 1);
    });
    return counts;
  }, [projectsQuery.data]);

  const documentCounts = useMemo(() => {
    const counts = new Map<number, number>();
    const documents = documentsListQuery.data?.items ?? [];
    documents.forEach((document) => {
      counts.set(document.initiative_id, (counts.get(document.initiative_id) ?? 0) + 1);
    });
    return counts;
  }, [documentsListQuery.data]);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newColor, setNewColor] = useState(DEFAULT_INITIATIVE_COLOR);
  const lastConsumedParams = useRef<string>("");

  // Check for query params to open create dialog (consume once)
  useEffect(() => {
    const shouldCreate = searchParams.create === "true";
    const paramKey = `${shouldCreate}`;

    if (shouldCreate && paramKey !== lastConsumedParams.current) {
      lastConsumedParams.current = paramKey;
      setCreateDialogOpen(true);
    }
  }, [searchParams]);

  const createInitiative = useCreateInitiative();

  const handleCreateInitiative = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = newName.trim();
    if (!trimmedName) {
      toast.error(t("createDialog.nameRequired"));
      return;
    }
    createInitiative.mutate(
      {
        name: trimmedName,
        description: newDescription.trim() || undefined,
        color: newColor,
      },
      {
        onSuccess: () => {
          setCreateDialogOpen(false);
          setNewName("");
          setNewDescription("");
          setNewColor(DEFAULT_INITIATIVE_COLOR);
        },
      }
    );
  };

  const renderMembershipBadge = (initiative: Initiative) => {
    const membership = initiative.members.find((member) => member.user.id === user?.id);
    if (membership) {
      const roleLabel = membership.role === "project_manager" ? projectManagerLabel : memberLabel;
      return <Badge variant="secondary">{roleLabel}</Badge>;
    }
    if (isGuildAdmin) {
      return <Badge variant="outline">{guildAdminLabel}</Badge>;
    }
    return null;
  };

  return (
    <PullToRefresh onRefresh={handleRefresh}>
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
            <p className="text-muted-foreground text-sm">{t("subtitle")}</p>
          </div>
          {canCreateInitiatives ? (
            <Button onClick={() => setCreateDialogOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("newInitiative")}
            </Button>
          ) : null}
        </div>

        {!activeGuild ? (
          <Card>
            <CardHeader>
              <CardTitle>{t("selectGuild")}</CardTitle>
              <CardDescription>{t("selectGuildDescription")}</CardDescription>
            </CardHeader>
          </Card>
        ) : null}

        {initiativesQuery.isLoading ? (
          <div className="text-muted-foreground flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("loading")}
          </div>
        ) : null}

        {initiativesQuery.isError ? (
          <p className="text-destructive text-sm">{t("loadError")}</p>
        ) : null}

        {!initiativesQuery.isLoading && !initiativesQuery.isError && activeGuild ? (
          visibleInitiatives.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2">
              {visibleInitiatives.map((initiative) => (
                <Card key={initiative.id} className="shadow-sm">
                  <CardHeader className="space-y-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <InitiativeColorDot color={initiative.color} />
                        <CardTitle className="text-xl">{initiative.name}</CardTitle>
                      </div>
                      {renderMembershipBadge(initiative)}
                    </div>
                    {initiative.description ? (
                      <Markdown content={initiative.description} className="text-sm" />
                    ) : (
                      <CardDescription className="text-sm">{t("noDescription")}</CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="text-muted-foreground text-sm">
                    <div className="mt-3 space-y-1 text-xs font-medium">
                      <p>
                        {t("members")}{" "}
                        <span className="font-semibold">{initiative.members.length}</span>
                      </p>
                      <p>
                        {t("projectsLabel")}{" "}
                        <span className="font-semibold">
                          {projectsQuery.isLoading ? "…" : (projectCounts.get(initiative.id) ?? 0)}
                        </span>
                      </p>
                      <p>
                        {t("documentsLabel")}{" "}
                        <span className="font-semibold">
                          {documentsListQuery.isLoading
                            ? "…"
                            : (documentCounts.get(initiative.id) ?? 0)}
                        </span>
                      </p>
                    </div>
                  </CardContent>
                  <CardFooter>
                    <Button asChild variant="outline" size="sm">
                      <Link to={gp(`/initiatives/${initiative.id}`)}>{t("openInitiative")}</Link>
                    </Button>
                  </CardFooter>
                </Card>
              ))}
            </div>
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>{t("noInitiatives")}</CardTitle>
                <CardDescription>{t("noInitiativesDescription")}</CardDescription>
              </CardHeader>
              {canCreateInitiatives ? (
                <CardFooter>
                  <Button onClick={() => setCreateDialogOpen(true)}>{t("createInitiative")}</Button>
                </CardFooter>
              ) : null}
            </Card>
          )
        ) : null}

        {canCreateInitiatives ? (
          <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
            <DialogContent className="bg-card max-h-screen overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{t("createDialog.title")}</DialogTitle>
                <DialogDescription>{t("createDialog.description")}</DialogDescription>
              </DialogHeader>
              <form className="space-y-4" onSubmit={handleCreateInitiative}>
                <div className="space-y-2">
                  <Label htmlFor="new-initiative-name">{t("createDialog.nameLabel")}</Label>
                  <Input
                    id="new-initiative-name"
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder={t("createDialog.namePlaceholder")}
                    required
                    disabled={createInitiative.isPending}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="new-initiative-description">
                    {t("createDialog.descriptionLabel")}
                  </Label>
                  <Textarea
                    id="new-initiative-description"
                    value={newDescription}
                    onChange={(event) => setNewDescription(event.target.value)}
                    placeholder={t("createDialog.descriptionPlaceholder")}
                    rows={3}
                    disabled={createInitiative.isPending}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="new-initiative-color">{t("createDialog.colorLabel")}</Label>
                  <ColorPickerPopover
                    id="new-initiative-color"
                    value={newColor}
                    onChange={setNewColor}
                    triggerLabel="Adjust"
                    disabled={createInitiative.isPending}
                  />
                  <p className="text-muted-foreground text-xs">{t("createDialog.colorHint")}</p>
                </div>
                <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                  <Button type="submit" disabled={createInitiative.isPending}>
                    {createInitiative.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        {t("createDialog.creating")}
                      </>
                    ) : (
                      t("createDialog.submit")
                    )}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        ) : null}
      </div>
    </PullToRefresh>
  );
};
