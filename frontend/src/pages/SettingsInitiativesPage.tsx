import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronsUpDown,
  CircleAlert,
  Loader2,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeListRead, UserGuildMember } from "@/api/generated/initiativeAPI.schemas";
import { DeleteInitiativeDialog } from "@/components/initiatives/DeleteInitiativeDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command";
import { DataTable } from "@/components/ui/data-table";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useArchiveEntity, useUnarchiveEntity } from "@/hooks/useArchive";
import { useGuilds } from "@/hooks/useGuilds";
import { useInitiativeRoles } from "@/hooks/useInitiativeRoles";
import {
  useAddInitiativeMember,
  useDeleteInitiative,
  useGuildInitiatives,
  useInitiative,
  useRemoveInitiativeMember,
  useUpdateInitiativeMember,
} from "@/hooks/useInitiatives";
import { useUsers } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { isAdminRole } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

/** An initiative's headcount, read from its roster. */
const InitiativeMemberCountCell = ({ initiativeId }: { initiativeId: number }) => {
  const { t } = useTranslation("initiatives");
  const { data } = useInitiative(initiativeId);
  if (!data) {
    return <Skeleton className="h-4 w-16" />;
  }
  return (
    <span className="text-muted-foreground text-sm">
      {t("manage.memberCount", { count: data.members.length })}
    </span>
  );
};

/**
 * Per-row project-manager picker — how a guild admin staffs an initiative, and
 * how they put one in their own sidebar (tick yourself).
 *
 * Ticking someone promotes them: an existing member's role changes, a
 * non-member gets a membership row. Unticking only takes the manager role away
 * — they stay in the initiative with the built-in member role. A guild admin is
 * the exception: they cannot hold a standard role, so unticking removes their
 * row (which is also how they leave an initiative they added themselves to).
 */
const InitiativeManagersCell = ({
  initiative,
  candidates,
  adminUserIds,
}: {
  initiative: InitiativeListRead;
  candidates: UserGuildMember[];
  adminUserIds: Set<number>;
}) => {
  const { t } = useTranslation(["initiatives", "common"]);
  const [open, setOpen] = useState(false);
  const rolesQuery = useInitiativeRoles(initiative.id);
  const rosterQuery = useInitiative(initiative.id);

  // The project manager by name first: moderator is a manager role too, and
  // this column staffs an initiative rather than hands out Full access.
  const managerRole = useMemo(
    () =>
      rolesQuery.data?.find((role) => role.name === "project_manager") ??
      rolesQuery.data?.find((role) => role.is_manager),
    [rolesQuery.data]
  );
  const memberRole = useMemo(
    () => rolesQuery.data?.find((role) => role.name === "member"),
    [rolesQuery.data]
  );

  const managerIds = useMemo(
    () =>
      new Set((rosterQuery.data?.members ?? []).filter((m) => m.is_manager).map((m) => m.user.id)),
    [rosterQuery.data]
  );
  const memberIds = useMemo(
    () => new Set((rosterQuery.data?.members ?? []).map((m) => m.user.id)),
    [rosterQuery.data]
  );

  const onError = (error: unknown) => {
    toast.error(getErrorMessage(error, "initiatives:manage.managersError"));
  };
  const onSuccess = () => {
    toast.success(t("manage.managersUpdated"));
  };
  const addMember = useAddInitiativeMember({ onSuccess, onError });
  const updateMember = useUpdateInitiativeMember({ onSuccess, onError });
  const removeMember = useRemoveInitiativeMember({ onSuccess, onError });
  const pending = addMember.isPending || updateMember.isPending || removeMember.isPending;

  const toggle = (userId: number) => {
    if (!managerRole) {
      return;
    }
    if (!managerIds.has(userId)) {
      if (memberIds.has(userId)) {
        updateMember.mutate({
          initiativeId: initiative.id,
          userId,
          data: { role_id: managerRole.id },
        });
      } else {
        addMember.mutate({
          initiativeId: initiative.id,
          data: { user_id: userId, role_id: managerRole.id },
        });
      }
      return;
    }
    if (adminUserIds.has(userId) || !memberRole) {
      removeMember.mutate({ initiativeId: initiative.id, userId });
    } else {
      updateMember.mutate({
        initiativeId: initiative.id,
        userId,
        data: { role_id: memberRole.id },
      });
    }
  };

  if (rolesQuery.isLoading || rosterQuery.isLoading) {
    return <Skeleton className="h-9 w-36" />;
  }

  // An unusable picker must say so rather than sit on a spinner that never
  // resolves.
  if (rolesQuery.isError || rosterQuery.isError || !managerRole) {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex text-destructive">
              <CircleAlert className="h-4 w-4" />
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">{t("manage.managersUnavailable")}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  const selectedLabel =
    managerIds.size === 0
      ? t("manage.noManagers")
      : managerIds.size === 1
        ? getUserDisplayName(
            candidates.find((c) => managerIds.has(c.id)),
            t("manage.managerCount", { count: 1 })
          )
        : t("manage.managerCount", { count: managerIds.size });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          role="combobox"
          aria-expanded={open}
          aria-label={t("manage.managersColumn")}
          className="w-48 justify-between font-normal"
        >
          <span className={managerIds.size === 0 ? "text-muted-foreground" : undefined}>
            {selectedLabel}
          </span>
          {pending ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
          ) : (
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[280px] p-0">
        <Command>
          <CommandInput placeholder={t("common:search")} />
          <CommandEmpty>{t("manage.noCandidates")}</CommandEmpty>
          <CommandGroup className="max-h-64 overflow-y-auto">
            {candidates.map((candidate) => (
              <CommandItem
                key={candidate.id}
                value={getUserDisplayName(candidate)}
                disabled={pending}
                onSelect={() => toggle(candidate.id)}
              >
                <Check
                  className={cn(
                    "mr-2 h-4 w-4",
                    managerIds.has(candidate.id) ? "opacity-100" : "opacity-0"
                  )}
                />
                {getUserDisplayName(candidate)}
              </CommandItem>
            ))}
          </CommandGroup>
        </Command>
      </PopoverContent>
    </Popover>
  );
};

export const SettingsInitiativesPage = () => {
  const { t } = useTranslation(["initiatives", "common"]);
  const { activeGuild } = useGuilds();
  const isGuildAdmin = Boolean(activeGuild?.can.administer);

  // The guild-wide listing, not the admin's own memberships — this table is
  // where they manage initiatives they have not joined.
  const initiativesQuery = useGuildInitiatives({ enabled: isGuildAdmin });
  const deleteInitiative = useDeleteInitiative();
  const archiveInitiative = useArchiveEntity();
  const unarchiveInitiative = useUnarchiveEntity();

  // One roster fetch for the whole table; every row's manager picker reads it.
  const usersQuery = useUsers({ enabled: isGuildAdmin, staleTime: 5 * 60 * 1000 });
  const candidates = useMemo(
    () => (usersQuery.data ?? []).filter((candidate) => candidate.status !== "anonymized"),
    [usersQuery.data]
  );
  const adminUserIds = useMemo(
    () => new Set(candidates.filter((c) => isAdminRole(c.guild_role)).map((c) => c.id)),
    [candidates]
  );

  const [deleteTarget, setDeleteTarget] = useState<InitiativeListRead | null>(null);

  const toggleArchive = (initiative: InitiativeListRead) => {
    const nextArchived = initiative.archived_at === null;
    const mutation = nextArchived ? archiveInitiative : unarchiveInitiative;
    mutation.mutate(
      { entityType: "initiative", entityId: initiative.id },
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

  const columns: AppColumnDef<InitiativeListRead>[] = [
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
      cell: ({ row }) => <InitiativeMemberCountCell initiativeId={row.original.id} />,
    },
    {
      id: "managers",
      header: t("manage.managersColumn"),
      cell: ({ row }) => (
        <InitiativeManagersCell
          initiative={row.original}
          candidates={candidates}
          adminUserIds={adminUserIds}
        />
      ),
    },
    {
      id: "status",
      header: t("manage.statusColumn"),
      cell: ({ row }) =>
        row.original.archived_at !== null ? (
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
              disabled={archiveInitiative.isPending || unarchiveInitiative.isPending}
            >
              {initiative.archived_at !== null ? (
                <>
                  <ArchiveRestore className="h-4 w-4" />
                  {t("manage.unarchive")}
                </>
              ) : (
                <>
                  <Archive className="h-4 w-4" />
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
              <Trash2 className="h-4 w-4" />
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
