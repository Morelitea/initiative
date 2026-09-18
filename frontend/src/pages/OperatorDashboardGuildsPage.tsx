import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformGuildStorageRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildStatus } from "@/api/generated/initiativeAPI.schemas";
import { createPlatformGuildBillingServiceHandoffApiV1SettingsGuildsGuildIdBillingServiceHandoffPost } from "@/api/generated/settings/settings";
import { GuildOperatorSettingsSheet } from "@/components/admin/GuildOperatorSettingsSheet";
import { SkeletonRegion, TableSkeleton } from "@/components/skeletons/PageSkeletons";
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
import { usePlatformGuilds, useUpdateGuildStorage } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";
import type { AppColumnDef } from "@/lib/table";

// Storage caps are entered in binary GB (GiB) so a value round-trips cleanly
// with `formatBytes` (which is also 1024-based). The editor for them, and for
// every other operator setting, lives in GuildOperatorSettingsSheet.
const GuildBillingCell = ({ guild }: { guild: PlatformGuildStorageRead }) => {
  const { t, i18n } = useTranslation("settings");
  const { billing } = useAppConfig();
  const [opening, setOpening] = useState(false);

  const open = async () => {
    if (!billing) return;
    setOpening(true);
    const tab = window.open("about:blank", "_blank");
    if (tab) tab.opener = null;
    try {
      const { handoff_token } =
        await createPlatformGuildBillingServiceHandoffApiV1SettingsGuildsGuildIdBillingServiceHandoffPost(
          guild.id
        );
      const lang = i18n.resolvedLanguage ?? i18n.language;
      // The token rides in the fragment, which never leaves the browser. The
      // console reads the guild off the exchanged session, so the URL does not
      // name one — only the language carries over.
      const url = `${billing.url}/support?lang=${encodeURIComponent(
        lang
      )}#support_handoff=${encodeURIComponent(handoff_token)}`;
      if (tab) tab.location.href = url;
      else window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      tab?.close();
      toast.error(getErrorMessage(err, "settings:guilds.billing.openError"));
    } finally {
      setOpening(false);
    }
  };

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={open}
      disabled={opening}
      aria-label={t("guilds.billing.openLabel", { name: guild.name })}
    >
      {guild.tier_name ?? t("guilds.billing.noPlan")}
    </Button>
  );
};

// Ordered least → most restrictive for the dropdown.
const GUILD_STATUS_ORDER: GuildStatus[] = [
  GuildStatus.active,
  GuildStatus.read_only,
  GuildStatus.suspended,
];

/**
 * Lifecycle-status control for one guild. Changing to `suspended` (a soft
 * delete — members lose all access) is gated behind a confirm dialog; the
 * lighter transitions apply immediately. The change saves via the same
 * platform-guilds mutation and the list invalidates on success, so the Select
 * reflects the persisted status.
 */
const GuildStatusCell = ({ guild }: { guild: PlatformGuildStorageRead }) => {
  const { t } = useTranslation(["settings", "common"]);
  const [pendingSuspend, setPendingSuspend] = useState(false);

  const update = useUpdateGuildStorage({
    onSuccess: (row) => {
      toast.success(t("guilds.statusSaved", { name: row.name }));
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "settings:guilds.statusSaveError"));
    },
    // Close the confirm dialog only once the mutation settles, so its in-flight
    // state is actually observable (the dialog shows "please wait" while saving).
    onSettled: () => setPendingSuspend(false),
  });

  const apply = (status: GuildStatus) => {
    update.mutate({ guildId: guild.id, data: { status } });
  };

  const handleChange = (value: string) => {
    const next = value as GuildStatus;
    if (next === guild.status) return;
    if (next === GuildStatus.suspended) {
      setPendingSuspend(true); // confirm the soft delete first
      return;
    }
    apply(next);
  };

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
          {GUILD_STATUS_ORDER.map((status) => (
            <SelectItem key={status} value={status}>
              {t(`guilds.status.${status}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <ConfirmDialog
        open={pendingSuspend}
        onOpenChange={setPendingSuspend}
        title={t("guilds.suspendConfirm.title", { name: guild.name })}
        description={t("guilds.suspendConfirm.description")}
        confirmLabel={t("guilds.suspendConfirm.confirm")}
        cancelLabel={t("common:cancel")}
        destructive
        isLoading={update.isPending}
        onConfirm={() => apply(GuildStatus.suspended)}
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

  const guildsQuery = usePlatformGuilds({ enabled: canManageGuilds });
  const { billing } = useAppConfig();
  // Which community's operator settings are open. The sheet reads the row from
  // the query, so a save re-renders it with the saved values.
  const [managingId, setManagingId] = useState<number | null>(null);
  const managing = guildsQuery.data?.find((guild) => guild.id === managingId) ?? null;

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
    return <p className="text-muted-foreground text-sm">{t("guilds.adminOnly")}</p>;
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
          data={guildsQuery.data}
          getRowId={(guild) => String(guild.id)}
          enableFilterInput
          filterInputColumnKey="name"
          filterInputPlaceholder={t("guilds.filterByName")}
          enableResetSorting
          enablePagination
        />
        <p className="text-muted-foreground text-xs">{t("guilds.helpText")}</p>
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
