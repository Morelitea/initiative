import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import type { AccessLevel } from "./RolePermissionsCard";

export interface UserPermissionRow {
  user_id: number;
  displayName: string;
  email: string;
  level: AccessLevel;
  isOwner: boolean;
}

export interface MemberOption {
  id: number;
  full_name?: string | null;
  email: string;
}

interface UserPermissionsCardProps {
  userPermissions: UserPermissionRow[];
  availableMembers: MemberOption[];
  busy?: boolean;
  onAdd: (userId: number, level: "read" | "write") => void;
  onUpdateLevel: (userId: number, level: "read" | "write") => void;
  onRemove: (userId: number) => void;
  onAddAll: (level: "read" | "write") => void;
  onBulkUpdate: (userIds: number[], level: "read" | "write") => void;
  onBulkRemove: (userIds: number[]) => void;
  title?: string;
  description?: string;
}

export const UserPermissionsCard = ({
  userPermissions,
  availableMembers,
  busy = false,
  onAdd,
  onUpdateLevel,
  onRemove,
  onAddAll,
  onBulkUpdate,
  onBulkRemove,
  title,
  description,
}: UserPermissionsCardProps) => {
  const { t } = useTranslation("access");
  const [selectedUserId, setSelectedUserId] = useState<string>("");
  const [selectedLevel, setSelectedLevel] = useState<"read" | "write">("read");
  const [selectedRows, setSelectedRows] = useState<UserPermissionRow[]>([]);

  const columns: ColumnDef<UserPermissionRow>[] = useMemo(
    () => [
      {
        accessorKey: "displayName",
        header: t("memberColumn"),
        cell: ({ row }) => <span className="font-medium">{row.original.displayName}</span>,
      },
      {
        accessorKey: "email",
        header: t("emailColumn"),
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.email}</span>,
      },
      {
        accessorKey: "level",
        header: t("accessLevel"),
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <span className="text-muted-foreground">{t("permissionOwner")}</span>;
          }
          return (
            <Select
              value={row.original.level}
              onValueChange={(value) =>
                onUpdateLevel(row.original.user_id, value as "read" | "write")
              }
              disabled={busy}
            >
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("permissionRead")}</SelectItem>
                <SelectItem value="write">{t("permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
          );
        },
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("actions")}</div>,
        cell: ({ row }) => {
          if (row.original.isOwner) {
            return <div className="text-right text-muted-foreground text-xs">-</div>;
          }
          return (
            <div className="text-right">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-destructive"
                onClick={() => onRemove(row.original.user_id)}
                disabled={busy}
              >
                {t("remove")}
              </Button>
            </div>
          );
        },
      },
    ],
    [t, busy, onUpdateLevel, onRemove]
  );

  const handleAdd = () => {
    if (!selectedUserId) return;
    onAdd(Number(selectedUserId), selectedLevel);
    setSelectedUserId("");
    setSelectedLevel("read");
  };

  // Owner rows can't be bulk-changed/removed, so exclude them from both the
  // count and the action payloads to avoid a misleading "N selected".
  const selectableIds = selectedRows.filter((r) => !r.isOwner).map((r) => r.user_id);

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{title ?? t("userPermissions")}</CardTitle>
        <CardDescription>{description ?? t("userPermissionsDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {selectableIds.length > 0 && (
          <div className="flex items-center gap-3 rounded-md bg-muted p-3">
            <span className="font-medium text-sm">
              {t("selectedCount", { count: selectableIds.length })}
            </span>
            <Select
              onValueChange={(level) => {
                if (selectableIds.length > 0)
                  onBulkUpdate(selectableIds, level as "read" | "write");
                setSelectedRows([]);
              }}
              disabled={busy}
            >
              <SelectTrigger className="w-36">
                <SelectValue placeholder={t("changeAccess")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("permissionRead")}</SelectItem>
                <SelectItem value="write">{t("permissionWrite")}</SelectItem>
              </SelectContent>
            </Select>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => {
                if (selectableIds.length > 0) onBulkRemove(selectableIds);
                setSelectedRows([]);
              }}
              disabled={busy}
            >
              {busy ? t("removing") : t("remove")}
            </Button>
          </div>
        )}

        <DataTable
          columns={columns}
          data={userPermissions}
          getRowId={(row) => String(row.user_id)}
          enablePagination
          enableFilterInput
          filterInputColumnKey="displayName"
          filterInputPlaceholder={t("filterByName")}
          enableRowSelection
          onRowSelectionChange={setSelectedRows}
          onExitSelection={() => setSelectedRows([])}
        />

        <div className="space-y-2 pt-2">
          <Label>{t("addMember")}</Label>
          {availableMembers.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("allMembersHaveAccess")}</p>
          ) : (
            <div className="flex flex-wrap items-end gap-3">
              <SearchableCombobox
                items={availableMembers.map((m) => ({
                  value: String(m.id),
                  label: m.full_name?.trim() || m.email,
                }))}
                value={selectedUserId}
                onValueChange={setSelectedUserId}
                placeholder={t("selectMember")}
                emptyMessage={t("noMembersFound")}
                className="min-w-50"
              />
              <Select
                value={selectedLevel}
                onValueChange={(v) => setSelectedLevel(v as "read" | "write")}
              >
                <SelectTrigger className="w-32">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">{t("permissionRead")}</SelectItem>
                  <SelectItem value="write">{t("permissionWrite")}</SelectItem>
                </SelectContent>
              </Select>
              <Button type="button" onClick={handleAdd} disabled={!selectedUserId || busy}>
                {busy ? t("adding") : t("add")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => onAddAll(selectedLevel)}
                disabled={busy}
              >
                {busy ? t("addingAll") : t("addAll", { count: availableMembers.length })}
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
};
