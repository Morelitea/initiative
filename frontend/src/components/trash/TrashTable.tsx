import { formatDistanceToNow } from "date-fns";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  RestoreOwnerCandidate,
  TrashItem,
  TrashItemEntityType,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useGuildTrashList,
  useMyTrashList,
  usePurgeTrashEntity,
  useRestoreTrashEntity,
} from "@/hooks/useTrash";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

import { ReassignOwnerDialog } from "./ReassignOwnerDialog";

/**
 * `user` — the viewer's own deletions across every guild (personal settings).
 * `guild` — everything in the active guild's trash (guild-admin settings).
 */
type TrashVariant = "user" | "guild";

interface TrashTableProps {
  variant: TrashVariant;
  // Whether to show the admin-only "Delete now" column. The backend also
  // gates this; the column is hidden so non-admins don't see a button that
  // would always 403.
  showPurgeAction: boolean;
}

const formatRelative = (iso: string): string => {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return iso;
  }
};

export const TrashTable = ({ variant, showPurgeAction }: TrashTableProps) => {
  const { t } = useTranslation("trash");
  // Hooks must run unconditionally; pick the active query by variant. The
  // unused one is disabled so it never fires a request.
  const myTrash = useMyTrashList({ enabled: variant === "user" });
  const guildTrash = useGuildTrashList({ enabled: variant === "guild" });
  const { data, isLoading } = variant === "user" ? myTrash : guildTrash;

  const [reassignState, setReassignState] = useState<
    | { open: false }
    | {
        open: true;
        guildId: number;
        entityType: TrashItemEntityType;
        entityId: number;
        validOwners: RestoreOwnerCandidate[];
      }
  >({ open: false });

  const [purgeConfirm, setPurgeConfirm] = useState<
    | { open: false }
    | {
        open: true;
        guildId: number;
        entityType: TrashItemEntityType;
        entityId: number;
        name: string;
      }
  >({ open: false });

  const restoreMutation = useRestoreTrashEntity({
    onSuccess: (data, variables) => {
      if ("restored" in data) {
        toast.success(t("restoreSuccess"));
        setReassignState({ open: false });
      } else if ("needs_reassignment" in data) {
        setReassignState({
          open: true,
          guildId: variables.guildId,
          entityType: variables.entityType,
          entityId: variables.entityId,
          validOwners: data.valid_owners ?? [],
        });
      }
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "trash:restoreError"));
    },
  });

  const purgeMutation = usePurgeTrashEntity({
    onSuccess: () => {
      toast.success(t("purgeSuccess"));
      setPurgeConfirm({ open: false });
    },
    onError: (err) => {
      toast.error(getErrorMessage(err, "trash:purgeError"));
    },
  });

  const items = useMemo(() => data?.items ?? [], [data]);

  if (isLoading) {
    return (
      <p className="text-muted-foreground text-sm">
        {t("common:loading", { defaultValue: "Loading..." })}
      </p>
    );
  }

  if (items.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("empty")}</p>;
  }

  const handleRestoreClick = (item: TrashItem) => {
    restoreMutation.mutate({
      guildId: item.guild_id,
      entityType: item.entity_type,
      entityId: item.entity_id,
    });
  };

  const handleReassignConfirm = (newOwnerId: number) => {
    if (!reassignState.open) return;
    restoreMutation.mutate({
      guildId: reassignState.guildId,
      entityType: reassignState.entityType,
      entityId: reassignState.entityId,
      body: { new_owner_id: newOwnerId },
    });
  };

  const handlePurgeConfirm = () => {
    if (!purgeConfirm.open) return;
    purgeMutation.mutate({
      guildId: purgeConfirm.guildId,
      entityType: purgeConfirm.entityType,
      entityId: purgeConfirm.entityId,
    });
  };

  return (
    <>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("columnType")}</TableHead>
              <TableHead>{t("columnName")}</TableHead>
              <TableHead>{t("columnDeletedBy")}</TableHead>
              <TableHead>{t("columnDeletedAt")}</TableHead>
              <TableHead>{t("columnPurgeAt")}</TableHead>
              <TableHead className="text-right">{t("columnActions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={`${item.entity_type}-${item.entity_id}`}>
                <TableCell>
                  <Badge variant="secondary">{t(`entityType.${item.entity_type}` as const)}</Badge>
                </TableCell>
                <TableCell className="font-medium">{item.name || `#${item.entity_id}`}</TableCell>
                <TableCell className="text-muted-foreground">{item.deleted_by_display}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatRelative(item.deleted_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {item.purge_at ? formatRelative(item.purge_at) : t("neverPurges")}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleRestoreClick(item)}
                      disabled={restoreMutation.isPending}
                    >
                      {t("restoreButton")}
                    </Button>
                    {showPurgeAction && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() =>
                          setPurgeConfirm({
                            open: true,
                            guildId: item.guild_id,
                            entityType: item.entity_type,
                            entityId: item.entity_id,
                            name: item.name || `#${item.entity_id}`,
                          })
                        }
                        disabled={purgeMutation.isPending}
                      >
                        {t("deleteNowButton")}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {reassignState.open && (
        <ReassignOwnerDialog
          open={reassignState.open}
          onOpenChange={(open) => !open && setReassignState({ open: false })}
          entityType={reassignState.entityType}
          validOwners={reassignState.validOwners}
          onConfirm={handleReassignConfirm}
          isPending={restoreMutation.isPending}
        />
      )}

      {purgeConfirm.open && (
        <ConfirmDialog
          open={purgeConfirm.open}
          onOpenChange={(open) => !open && setPurgeConfirm({ open: false })}
          title={t("deleteNowConfirmTitle")}
          description={t("deleteNowConfirmDescription", {
            type: t(`entityType.${purgeConfirm.entityType}` as const).toLowerCase(),
          })}
          confirmLabel={t("deleteNowConfirmAction")}
          onConfirm={handlePurgeConfirm}
          isLoading={purgeMutation.isPending}
          destructive
        />
      )}
    </>
  );
};
