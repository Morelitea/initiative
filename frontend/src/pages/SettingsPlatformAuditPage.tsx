import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AuditActor, AuditEventRead } from "@/api/generated/initiativeAPI.schemas";
import { UserHandle } from "@/components/UserHandle";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { usePlatformAuditEvents } from "@/hooks/useAdmin";
import { formatDateTime } from "@/lib/formatDate";
import type { AppColumnDef } from "@/lib/table";

const PAGE_SIZE = 50;

/**
 * Someone who may no longer exist.
 *
 * An entry holds ids, so a name is resolved when the board is read — and an
 * account erased since simply resolves to nothing. Showing the id is the honest
 * answer there: the record of what was done to them is the point, and it
 * outlives them.
 */
const Party = ({ party }: { party: AuditActor | null | undefined }) => {
  const { t } = useTranslation("settings");
  if (!party) return <span className="text-muted-foreground">—</span>;
  if (!party.username) {
    return (
      <span className="text-muted-foreground italic">
        {t("audit.departedAccount", { id: party.id })}
      </span>
    );
  }
  return <UserHandle user={party} />;
};

export const SettingsPlatformAuditPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const [page, setPage] = useState(1);
  const [targetFilter, setTargetFilter] = useState("");

  const targetUserId = Number.parseInt(targetFilter, 10);
  const params = {
    page,
    page_size: PAGE_SIZE,
    ...(Number.isFinite(targetUserId) ? { target_user_id: targetUserId } : {}),
  };

  const { data, isLoading } = usePlatformAuditEvents(params);

  const columns: AppColumnDef<AuditEventRead>[] = [
    {
      accessorKey: "occurred_at",
      header: t("audit.whenColumn"),
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-muted-foreground text-sm">
          {formatDateTime(row.original.occurred_at)}
        </span>
      ),
    },
    {
      accessorKey: "event_type",
      header: t("audit.actionColumn"),
      cell: ({ row }) => (
        <span className="text-sm">
          {t(`audit.actions.${row.original.event_type}` as never, {
            defaultValue: row.original.event_type,
          })}
        </span>
      ),
    },
    {
      accessorKey: "actor",
      header: t("audit.actorColumn"),
      cell: ({ row }) => <Party party={row.original.actor} />,
    },
    {
      accessorKey: "target_user",
      header: t("audit.subjectColumn"),
      cell: ({ row }) => <Party party={row.original.target_user} />,
    },
  ];

  const items = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("audit.title")}</CardTitle>
        <CardDescription>{t("audit.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Input
          value={targetFilter}
          onChange={(event) => {
            setTargetFilter(event.target.value.replace(/[^0-9]/g, ""));
            setPage(1);
          }}
          placeholder={t("audit.subjectFilterPlaceholder")}
          className="max-w-xs"
          inputMode="numeric"
        />

        <DataTable columns={columns} data={items} />

        {!isLoading && items.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("audit.empty")}</p>
        )}

        {(data?.has_prev || data?.has_next) && (
          <div className="flex items-center justify-between">
            <Button
              variant="outline"
              size="sm"
              disabled={!data?.has_prev}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              {t("common:previous")}
            </Button>
            <span className="text-muted-foreground text-sm">
              {t("audit.pageOf", { page: data?.page ?? 1, total: data?.total_count ?? 0 })}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!data?.has_next}
              onClick={() => setPage((p) => p + 1)}
            >
              {t("common:next")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
