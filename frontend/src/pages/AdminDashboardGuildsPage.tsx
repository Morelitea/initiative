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
import { cn } from "@/lib/utils";

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

/** Parse the user-limit input into the value to send, or flag an invalid entry. */
const parseUserLimitInput = (raw: string): { limit: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { limit: null, invalid: false }; // blank = unlimited
  const n = Number(trimmed);
  // A member cap must be a whole number >= 1 (a guild always has its creator).
  if (!Number.isInteger(n) || n < 1) return { limit: null, invalid: true };
  return { limit: n, invalid: false };
};

/** Render a stored user cap back into a tidy input string ("" = unlimited). */
const userLimitToInput = (limit: number | null): string => (limit == null ? "" : String(limit));

/**
 * The "Users" cell: current member count over an inline-editable cap, rendering
 * the `3/unlimited` (or `3/10`) display the operator reads at a glance. The cap
 * input auto-saves on blur (and Enter); blank means unlimited and a bad entry
 * reverts. When a guild is over its cap (e.g. the cap was lowered below the
 * current headcount) the count is flagged — existing members are never removed,
 * only new joins are blocked.
 */
const GuildUserLimitCell = ({ guild }: { guild: PlatformGuildStorageRead }) => {
  const { t } = useTranslation("settings");
  const stored = guild.max_users ?? null;
  const [draft, setDraft] = useState(() => userLimitToInput(stored));

  const update = useUpdateGuildStorage({
    onSuccess: (row) => {
      setDraft(userLimitToInput(row.max_users ?? null));
      toast.success(t("guilds.usersSaved", { name: row.name }));
    },
    onError: (err) => {
      setDraft(userLimitToInput(stored)); // revert to the last persisted value
      toast.error(getErrorMessage(err, "settings:guilds.usersSaveError"));
    },
  });

  const commit = () => {
    const { limit, invalid } = parseUserLimitInput(draft);
    if (invalid) {
      setDraft(userLimitToInput(stored));
      return;
    }
    if (limit === stored) {
      setDraft(userLimitToInput(stored)); // normalize formatting (e.g. "10 " -> "10")
      return;
    }
    update.mutate({ guildId: guild.id, data: { max_users: limit } });
  };

  const overLimit = stored != null && guild.member_count > stored;

  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn(
          "tabular-nums",
          overLimit ? "font-medium text-destructive" : "text-muted-foreground"
        )}
        title={overLimit ? t("guilds.overLimitHint", { name: guild.name }) : undefined}
      >
        {guild.member_count}
      </span>
      <span className="text-muted-foreground">/</span>
      <Input
        type="number"
        min={1}
        step={1}
        inputMode="numeric"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
        placeholder={t("guilds.unlimitedPlaceholder")}
        aria-label={t("guilds.userLimitInputLabel", { name: guild.name })}
        disabled={update.isPending}
        className="w-28"
      />
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
      header: t("guilds.columns.users"),
      cell: ({ row }) => <GuildUserLimitCell guild={row.original} />,
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
