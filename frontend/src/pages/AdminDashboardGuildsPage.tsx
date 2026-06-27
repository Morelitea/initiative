import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformGuildStorageRead } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { usePlatformGuilds, useUpdateGuildStorage } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

// Storage caps are entered in binary GB (GiB) so a value round-trips cleanly
// with `formatBytes` (which is also 1024-based).
const GIB = 1024 ** 3;

/** Parse the GB input into the byte value to send, or flag an invalid entry. */
const parseGbInput = (raw: string): { bytes: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { bytes: null, invalid: false }; // blank = unlimited
  const gb = Number(trimmed);
  if (!Number.isFinite(gb) || gb < 0) return { bytes: null, invalid: true };
  return { bytes: Math.round(gb * GIB), invalid: false };
};

/** Render a stored byte cap back into a tidy GB input string ("" = unlimited). */
const bytesToGbInput = (bytes: number | null): string =>
  bytes == null ? "" : String(Number.parseFloat((bytes / GIB).toFixed(3)));

/**
 * Inline editor for one guild's storage cap. The input is pre-filled with the
 * guild's current cap (in GB) — editing it in place is how you change it. It
 * auto-saves on blur (and on Enter), the same way the user interface settings
 * commit a numeric field; blank means unlimited. A bad entry reverts.
 */
const GuildStorageCell = ({ guild }: { guild: PlatformGuildStorageRead }) => {
  const { t } = useTranslation("settings");
  const stored = guild.max_storage_bytes ?? null;
  const [draft, setDraft] = useState(() => bytesToGbInput(stored));

  const update = useUpdateGuildStorage({
    onSuccess: (row) => {
      setDraft(bytesToGbInput(row.max_storage_bytes));
      toast.success(t("guilds.saved", { name: row.name }));
    },
    onError: (err) => {
      setDraft(bytesToGbInput(stored)); // revert to the last persisted value
      toast.error(getErrorMessage(err, "settings:guilds.saveError"));
    },
  });

  const commit = () => {
    const { bytes, invalid } = parseGbInput(draft);
    // A malformed entry snaps back to the persisted value rather than saving.
    if (invalid) {
      setDraft(bytesToGbInput(stored));
      return;
    }
    if (bytes === stored) {
      setDraft(bytesToGbInput(stored)); // normalize formatting (e.g. "10.0" -> "10")
      return;
    }
    update.mutate({ guildId: guild.id, data: { max_storage_bytes: bytes } });
  };

  return (
    <div className="relative w-36">
      <Input
        type="number"
        min={0}
        step="any"
        inputMode="decimal"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        placeholder={t("guilds.unlimitedPlaceholder")}
        aria-label={t("guilds.limitInputLabel", { name: guild.name })}
        disabled={update.isPending}
        className="pr-9"
      />
      <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground text-xs">
        GB
      </span>
    </div>
  );
};

export const AdminDashboardGuildsPage = () => {
  const { t } = useTranslation("settings");
  const { user } = useAuth();
  const canManageGuilds = hasCapability(user, Capability.guildsManage);

  const guildsQuery = usePlatformGuilds({ enabled: canManageGuilds });

  const columns: ColumnDef<PlatformGuildStorageRead>[] = [
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
      header: t("guilds.columns.members"),
      cell: ({ row }) => (
        <span className="text-muted-foreground tabular-nums">{row.original.member_count}</span>
      ),
    },
    {
      id: "storage",
      header: t("guilds.columns.storageLimit"),
      enableSorting: false,
      cell: ({ row }) => <GuildStorageCell guild={row.original} />,
    },
  ];

  if (!canManageGuilds) {
    return <p className="text-muted-foreground text-sm">{t("guilds.adminOnly")}</p>;
  }

  if (guildsQuery.isLoading) {
    return <p className="text-muted-foreground text-sm">{t("guilds.loading")}</p>;
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
    </Card>
  );
};
