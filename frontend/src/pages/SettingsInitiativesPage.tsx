import type { ColumnDef } from "@tanstack/react-table";
import { Archive, ArchiveRestore, CircleAlert, Loader2, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativeRoles, useUpdateRole } from "@/hooks/useInitiativeRoles";
import { useDeleteInitiative, useInitiatives, useUpdateInitiative } from "@/hooks/useInitiatives";
import { toast } from "@/lib/chesterToast";

/**
 * Per-row "PM full access" toggle. The full-access flag is
 * ``override_share_restrictions`` on the built-in project_manager role — the
 * single source of truth — so this cell reads the initiative's roles and
 * toggles that role directly (no denormalized copy on the initiative).
 */
const PmFullAccessCell = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation("initiatives");
  const rolesQuery = useInitiativeRoles(initiativeId);
  const updateRole = useUpdateRole(initiativeId);

  const pmRole = useMemo(
    () => rolesQuery.data?.find((role) => role.name === "project_manager"),
    [rolesQuery.data]
  );

  if (rolesQuery.isLoading) {
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />;
  }

  // A failed roles fetch (or a missing PM role) must NOT fall through to the
  // loading spinner — that would spin forever. Show a clear, hoverable error
  // marker instead so the admin knows this one row's access state is unknown.
  if (rolesQuery.isError || !pmRole) {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex text-destructive">
              <CircleAlert className="h-4 w-4" />
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">{t("manage.fullAccessUnavailable")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          {/* Span keeps a hoverable trigger even while the Switch is disabled
              (disabled controls don't emit pointer events). */}
          <span className="inline-flex">
            <Switch
              aria-label={t("settings.fullAccess")}
              checked={pmRole.override_share_restrictions}
              disabled={updateRole.isPending}
              onCheckedChange={(checked) =>
                updateRole.mutate({
                  roleId: pmRole.id,
                  data: { override_share_restrictions: checked },
                })
              }
            />
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">{t("settings.fullAccessDescription")}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const SettingsInitiativesPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { activeGuild } = useGuilds();
  const isGuildAdmin = activeGuild?.role === "admin";

  const initiativesQuery = useInitiatives({ enabled: isGuildAdmin });
  const updateInitiative = useUpdateInitiative();
  const deleteInitiative = useDeleteInitiative();

  const [deleteTarget, setDeleteTarget] = useState<InitiativeRead | null>(null);

  const toggleArchive = (initiative: InitiativeRead) => {
    const nextArchived = !initiative.is_archived;
    updateInitiative.mutate(
      { initiativeId: initiative.id, data: { is_archived: nextArchived } },
      {
        onSuccess: () => {
          toast.success(
            nextArchived
              ? t("manage.archivedToast", { name: initiative.name })
              : t("manage.unarchivedToast", { name: initiative.name })
          );
        },
      }
    );
  };

  const confirmDelete = () => {
    if (!deleteTarget) return;
    deleteInitiative.mutate(deleteTarget.id, {
      onSuccess: () => {
        toast.success(t("manage.deletedToast", { name: deleteTarget.name }));
        setDeleteTarget(null);
      },
    });
  };

  const columns: ColumnDef<InitiativeRead>[] = [
    {
      accessorKey: "id",
      header: t("manage.idColumn"),
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground text-sm">{row.original.id}</span>
      ),
    },
    {
      accessorKey: "name",
      header: t("manage.nameColumn"),
      cell: ({ row }) => {
        const initiative = row.original;
        return (
          <div className="flex items-center gap-2">
            {initiative.color ? (
              <span
                className="inline-block h-3 w-3 shrink-0 rounded-full"
                style={{ backgroundColor: initiative.color }}
                aria-hidden
              />
            ) : null}
            <span className="font-medium">{initiative.name}</span>
            {initiative.is_default ? (
              <Badge variant="secondary" className="text-xs">
                {t("manage.default")}
              </Badge>
            ) : null}
          </div>
        );
      },
    },
    {
      id: "members",
      header: t("manage.membersColumn"),
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm">
          {t("manage.memberCount", { count: row.original.members.length })}
        </span>
      ),
    },
    {
      id: "full_access",
      header: t("manage.fullAccessColumn"),
      cell: ({ row }) => <PmFullAccessCell initiativeId={row.original.id} />,
    },
    {
      id: "status",
      header: t("manage.statusColumn"),
      cell: ({ row }) =>
        row.original.is_archived ? (
          <Badge variant="outline" className="text-xs">
            {t("manage.archived")}
          </Badge>
        ) : (
          <Badge className="text-xs">{t("manage.active")}</Badge>
        ),
    },
    {
      id: "actions",
      header: t("manage.actionsColumn"),
      cell: ({ row }) => {
        const initiative = row.original;
        return (
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => toggleArchive(initiative)}
              disabled={updateInitiative.isPending}
            >
              {initiative.is_archived ? (
                <>
                  <ArchiveRestore className="mr-1.5 h-4 w-4" />
                  {t("manage.unarchive")}
                </>
              ) : (
                <>
                  <Archive className="mr-1.5 h-4 w-4" />
                  {t("manage.archive")}
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => setDeleteTarget(initiative)}
              disabled={initiative.is_default}
              title={initiative.is_default ? t("manage.deleteDefaultHint") : undefined}
            >
              <Trash2 className="mr-1.5 h-4 w-4" />
              {t("manage.delete")}
            </Button>
          </div>
        );
      },
    },
  ];

  if (!isGuildAdmin) {
    return <p className="text-muted-foreground text-sm">{t("manage.adminRequired")}</p>;
  }

  if (initiativesQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("manage.loading")}</p>;
  }

  if (initiativesQuery.isError || !initiativesQuery.data) {
    return <p className="text-destructive text-sm">{t("manage.loadError")}</p>;
  }

  return (
    <div className="space-y-6">
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>{t("manage.title")}</CardTitle>
          <CardDescription>{t("manage.description")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <DataTable
            columns={columns}
            data={initiativesQuery.data}
            enableFilterInput
            filterInputColumnKey="name"
            filterInputPlaceholder={t("manage.filterByName")}
            enableResetSorting
            enablePagination
          />
        </CardContent>
      </Card>

      <DeleteInitiativeDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        initiativeName={deleteTarget?.name ?? ""}
        isDeleting={deleteInitiative.isPending}
        onConfirm={confirmDelete}
      />
    </div>
  );
};
