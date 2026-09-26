import type { PaginationState, SortingState } from "@tanstack/react-table";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformGuildStorageRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildStatus } from "@/api/generated/initiativeAPI.schemas";
import { BillingConsoleButton } from "@/components/platform/BillingConsoleButton";
import { GuildOperatorSettingsSheet } from "@/components/platform/GuildOperatorSettingsSheet";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { DataTable } from "@/components/ui/data-table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { usePlatformGuilds, useUpdateGuildStorage } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";

// Storage caps are entered in binary GB (GiB) so a value round-trips cleanly
// with `formatBytes` (which is also 1024-based). The editor for them, and for
// every other operator setting, lives in GuildOperatorSettingsSheet.
const GuildBillingCell = ({ guild }: { guild: PlatformGuildStorageRead }) => {
  const { t } = useTranslation("settings");
  return (
    <div className="flex items-center gap-1">
      <BillingConsoleButton
        guild={guild}
        console="support"
        size="sm"
        variant="outline"
        aria-label={t("guilds.billing.openLabel", { name: guild.name })}
      >
        {guild.tier_name ?? t("guilds.billing.noPlan")}
      </BillingConsoleButton>
      <BillingConsoleButton
        guild={guild}
        console="operator"
        size="sm"
        variant="ghost"
        aria-label={t("guilds.billing.operatorLabel", { name: guild.name })}
      >
        {t("guilds.billing.operations")}
      </BillingConsoleButton>
    </div>
  );
};

/**
 * Lifecycle-status control for one guild. Changing to `suspended` or
 * `on_hold` (everyone in it loses all access) is gated behind a confirm
 * dialog; the lighter transitions apply immediately. The change saves via the same platform-guilds mutation
 * and the list invalidates on success, so the Select reflects the persisted
 * status.
 *
 * The choices are the row's own `status_choices`, which the server works out:
 * every settable status on a deployment that sets plans by hand, and only a
 * suspension (and lifting it, back to the status billing last set) where
 * billing sets them.
 *
 * A deleted community has no control at all — it shows a tag instead. Deleted
 * is not a status you set: it is reached by deleting the community and left by
 * restoring it, both of which do more than move this field, so the only way
 * back is the wizard under Manage.
 */
const GuildStatusCell = ({ guild }: { guild: PlatformGuildStorageRead }) => {
  const { t } = useTranslation(["settings", "common"]);
  // Suspending and putting on hold both take everyone out of the community,
  // so each is confirmed before it is applied.
  const [pending, setPending] = useState<GuildStatus | null>(null);

  const update = useUpdateGuildStorage({
    onSuccess: (row) => {
      toast.success(t("guilds.statusSaved", { name: row.name }));
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:guilds.statusSaveError"));
    },
    // Close the confirm dialog only once the mutation settles, so its in-flight
    // state is actually observable (the dialog shows "please wait" while saving).
    onSettled: () => setPending(null),
  });

  const apply = (status: GuildStatus) => {
    update.mutate({ guildId: guild.id, data: { status } });
  };

  const handleChange = (value: string) => {
    const next = value as GuildStatus;
    if (next === guild.status) return;
    if (next === GuildStatus.suspended || next === GuildStatus.on_hold) {
      setPending(next);
      return;
    }
    apply(next);
  };

  if (guild.status === GuildStatus.deleted) {
    return <Badge variant="destructive">{t("guilds.status.deleted")}</Badge>;
  }

  return (
    <>
      <Select value={guild.status} onValueChange={handleChange} disabled={update.isPending}>
        <SelectTrigger
          className="w-36"
          aria-label={t("guilds.statusInputLabel", { name: guild.name })}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {guild.status_choices.map((status) => (
            <SelectItem key={status} value={status}>
              {t(`guilds.status.${status}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ConfirmDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        title={
          pending === GuildStatus.on_hold
            ? t("guilds.holdConfirm.title", { name: guild.name })
            : t("guilds.suspendConfirm.title", { name: guild.name })
        }
        description={
          pending === GuildStatus.on_hold
            ? t("guilds.holdConfirm.description")
            : t("guilds.suspendConfirm.description")
        }
        confirmLabel={
          pending === GuildStatus.on_hold
            ? t("guilds.holdConfirm.confirm")
            : t("guilds.suspendConfirm.confirm")
        }
        cancelLabel={t("common:cancel")}
        destructive
        isLoading={update.isPending}
        onConfirm={() => pending && apply(pending)}
      />
    </>
  );
};

/**
 * Per-guild sign-in entitlement toggle. Flipping it on lets the guild configure
 * its own login providers and onboard new accounts through them; withdrawing it
 * closes that config surface and stops new-account onboarding, but never deletes
 * providers or signs existing members out.
 */
export const OperatorDashboardGuildsPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageGuilds = hasCapability(user, Capability.guildsManage);

  // Searched, sorted and paged on the server, so the table holds one page of
  // the deployment's communities rather than all of them.
  const [draft, setDraft] = useState("");
  const search = useDebouncedValue(draft, 250);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const sort = sorting[0];
  const guildsQuery = usePlatformGuilds(
    {
      search: search.trim() || undefined,
      page,
      page_size: pageSize,
      ...(sort?.id === "id" || sort?.id === "name"
        ? { sort_by: sort.id, sort_dir: sort.desc ? ("desc" as const) : ("asc" as const) }
        : {}),
    },
    { enabled: canManageGuilds }
  );
  const rows = guildsQuery.data?.items ?? [];
  const totalCount = guildsQuery.data?.total_count ?? 0;
  const { billing } = useAppConfig();
  // Which community's operator settings are open. The sheet reads the row from
  // the query, so a save re-renders it with the saved values.
  const [managingId, setManagingId] = useState<number | null>(null);
  const managing = rows.find((guild) => guild.id === managingId) ?? null;

  const columns: AppColumnDef<PlatformGuildStorageRead>[] = [
    {
      accessorKey: "id",
      header: t("guilds.columns.id"),
      cell: ({ row }) => (
        <span className="font-mono text-muted-foreground text-sm">{row.original.id}</span>
      ),
    },
    {
      accessorKey: "name",
      header: t("guilds.columns.guild"),
      cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    },
    {
      accessorKey: "member_count",
      header: t("guilds.columns.users"),
      enableSorting: false,
      cell: ({ row }) => (
        <span className="text-sm tabular-nums">
          {row.original.max_users == null
            ? row.original.member_count
            : `${row.original.member_count} / ${row.original.max_users}`}
        </span>
      ),
    },
    {
      id: "storage",
      header: t("guilds.columns.storageLimit"),
      enableSorting: false,
      cell: ({ row }) => (
        <span className="text-muted-foreground text-sm tabular-nums">
          {row.original.max_storage_bytes == null
            ? t("guilds.unlimited")
            : `${Number((row.original.max_storage_bytes / 1024 ** 3).toFixed(2))} GB`}
        </span>
      ),
    },
    {
      id: "manage",
      header: "",
      enableSorting: false,
      cell: ({ row }) => (
        <Button
          variant="outline"
          size="sm"
          onClick={() => setManagingId(row.original.id)}
          aria-label={t("guilds.sheet.openLabel", { name: row.original.name })}
        >
          {t("guilds.sheet.open")}
        </Button>
      ),
    },
    {
      id: "status",
      header: t("guilds.columns.status"),
      enableSorting: false,
      cell: ({ row }) => <GuildStatusCell guild={row.original} />,
    },
    // Only when this deployment links a billing portal AND the operator route
    // into it is wired — otherwise the button could only ever fail.
    ...(billing?.operator_handoff
      ? [
          {
            id: "billing",
            header: t("guilds.columns.billing"),
            enableSorting: false,
            cell: ({ row }) => <GuildBillingCell guild={row.original} />,
          } satisfies AppColumnDef<PlatformGuildStorageRead>,
        ]
      : []),
  ];

  if (!canManageGuilds) {
    return <p className="text-muted-foreground text-sm">{t("guilds.platformOnly")}</p>;
  }

  if (guildsQuery.isLoading) {
    return (
      <SkeletonRegion label={t("guilds.loading")}>
        <TableSkeleton rows={6} columns={5} />
      </SkeletonRegion>
    );
  }

  if (guildsQuery.isError || !guildsQuery.data) {
    return <p className="text-destructive text-sm">{t("guilds.loadError")}</p>;
  }

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("guilds.title")}</CardTitle>
        <CardDescription>{t("guilds.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <DataTable
          columns={columns}
          data={rows}
          getRowId={(guild) => String(guild.id)}
          enableFilterInput
          filterInputPlaceholder={t("guilds.filterByName")}
          filterValue={draft}
          onFilterValueChange={(value) => {
            setDraft(value);
            setPage(1);
          }}
          manualSorting
          sorting={sorting}
          onSortingChange={(next) => {
            setSorting(next);
            setPage(1);
          }}
          enableResetSorting
          enablePagination
          manualPagination
          pageCount={Math.max(1, Math.ceil(totalCount / pageSize))}
          rowCount={totalCount}
          pageIndex={page - 1}
          onPaginationChange={(next: PaginationState) => {
            if (next.pageSize !== pageSize) {
              setPageSize(next.pageSize);
              setPage(1);
            } else {
              setPage(next.pageIndex + 1);
            }
          }}
        />
        <p className="text-muted-foreground text-xs">
          {billing?.manages_plans ? t("guilds.helpTextBilling") : t("guilds.helpText")}
        </p>
      </CardContent>
      <GuildOperatorSettingsSheet
        guild={managing}
        open={managing !== null}
        onOpenChange={(next) => {
          if (!next) setManagingId(null);
        }}
      />
    </Card>
  );
};
