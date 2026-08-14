/**
 * Who reaches an outside system through this guild, and the levers for it.
 *
 * Installing an app is an admin decision, and so is who may use it. What an
 * admin gets here is governance, not inspection: which member connected as
 * which vendor account, when, and three ways to end it —
 *
 * - **Revoke** deletes that member's stored credential and tells the app to let
 *   go at the vendor. They may connect again.
 * - **Block** does the same and refuses the next attempt, for "this person
 *   should no longer reach that system through us" without uninstalling the app
 *   for everyone.
 * - **Revoke all** does it for every member at once, for a suspected app or
 *   vendor compromise, leaving the install and its configuration standing.
 *
 * Deliberately absent: the values. No admin workflow needs the bytes, and being
 * able to end someone's access is strictly more useful than being able to read
 * a token you could then use as them.
 */

import { Loader2, ShieldOff, UserX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AppConnectionSummary,
  AppMemberConnection,
  AppMemberDelegation,
} from "@/api/appConnections";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useBlockMemberConnection,
  useGuildAppMembers,
  useRevokeAllConnections,
  useRevokeAllDelegations,
  useRevokeMemberConnection,
  useRevokeMemberDelegation,
} from "@/hooks/useGuildAppDetail";
import { useUsers } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { localized } from "@/lib/widgets/widgetMeta";

export interface AppMembersPanelProps {
  appId: number;
  /** Rendered only for guild admins; the server refuses everyone else anyway. */
  enabled: boolean;
}

export function AppMembersPanel({ appId, enabled }: AppMembersPanelProps) {
  const { t } = useTranslation(["apps", "common"]);
  const membersQuery = useGuildAppMembers(appId, enabled);
  const usersQuery = useUsers();
  const revokeAll = useRevokeAllConnections(appId);
  const [confirmingRevokeAll, setConfirmingRevokeAll] = useState(false);

  if (!enabled) return null;
  if (membersQuery.isLoading) return <Skeleton className="h-24 w-full" />;

  const summary = membersQuery.data?.summary ?? [];
  const items = membersQuery.data?.items ?? [];
  const delegations = membersQuery.data?.delegations ?? [];

  if (!summary.length && !delegations.length) {
    return <p className="text-muted-foreground text-sm">{t("apps:members.noPersonal")}</p>;
  }

  const nameFor = (userId: number) =>
    usersQuery.data?.find((user) => user.id === userId)?.full_name ??
    t("apps:members.unknownMember", { id: userId });

  return (
    <div className="space-y-4">
      {summary.map((connection) => (
        <ConnectionMembers
          key={connection.connection_id}
          appId={appId}
          summary={connection}
          items={items.filter((item) => item.connection_id === connection.connection_id)}
          nameFor={nameFor}
        />
      ))}

      {/* The inbound direction, beside the outbound one: both answer "what does
          this app have of this member's", so an admin governing one finds the
          other in the same place. */}
      {delegations.length > 0 && (
        <MemberDelegations appId={appId} delegations={delegations} nameFor={nameFor} />
      )}

      {summary.length > 0 && (
        <div>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setConfirmingRevokeAll(true)}
            disabled={revokeAll.isPending}
          >
            {revokeAll.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {t("apps:members.revokeAll")}
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirmingRevokeAll}
        onOpenChange={setConfirmingRevokeAll}
        title={t("apps:members.revokeAllTitle")}
        description={t("apps:members.revokeAllBody")}
        confirmLabel={t("apps:members.revokeAll")}
        isLoading={revokeAll.isPending}
        destructive
        onConfirm={() =>
          revokeAll.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("apps:members.revokedAll"));
              setConfirmingRevokeAll(false);
            },
            onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
          })
        }
      />
    </div>
  );
}

/**
 * Who has authorized this app to act as them.
 *
 * An admin ends an authorization and cannot give one: the two buttons here both
 * revoke. Whose name the app may carry is answered by that person, so an admin
 * who takes it away has taken it away — they have not moved it to a setting
 * they control.
 */
function MemberDelegations({
  appId,
  delegations,
  nameFor,
}: {
  appId: number;
  delegations: AppMemberDelegation[];
  nameFor: (userId: number) => string;
}) {
  const { t } = useTranslation(["apps", "common"]);
  const revoke = useRevokeMemberDelegation(appId);
  const revokeAll = useRevokeAllDelegations(appId);
  const [confirming, setConfirming] = useState(false);

  const active = delegations.filter((row) => !row.revoked);

  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium text-sm">{t("apps:delegation.membersTitle")}</h3>
        <span className="text-muted-foreground text-xs">
          {t("apps:delegation.authorizedCount", { count: active.length })}
        </span>
      </header>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("apps:members.member")}</TableHead>
              <TableHead>{t("apps:delegation.levelColumn")}</TableHead>
              <TableHead>{t("apps:delegation.sinceColumn")}</TableHead>
              <TableHead className="text-right">{t("common:actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {delegations.map((row) => (
              <TableRow key={row.user_id}>
                <TableCell className="font-medium">{nameFor(row.user_id)}</TableCell>
                <TableCell>
                  {row.revoked ? (
                    <Badge variant="outline">{t("apps:delegation.withdrawnBadge")}</Badge>
                  ) : (
                    <Badge variant="secondary">
                      {row.can_write
                        ? t("apps:delegation.levelWrite")
                        : t("apps:delegation.levelRead")}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {new Date(
                    row.revoked ? (row.revoked_at ?? row.updated_at) : row.granted_at
                  ).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  {!row.revoked && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={revoke.isPending}
                      onClick={() =>
                        revoke.mutate(row.user_id, {
                          onSuccess: () => toast.success(t("apps:delegation.memberRevoked")),
                          onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
                        })
                      }
                    >
                      <UserX className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                      {t("apps:members.revoke")}
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {active.length > 0 && (
        <Button
          size="sm"
          variant="destructive"
          disabled={revokeAll.isPending}
          onClick={() => setConfirming(true)}
        >
          {revokeAll.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {t("apps:delegation.revokeAll")}
        </Button>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("apps:delegation.revokeAllTitle")}
        description={t("apps:delegation.revokeAllBody")}
        confirmLabel={t("apps:delegation.revokeAll")}
        isLoading={revokeAll.isPending}
        destructive
        onConfirm={() =>
          revokeAll.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("apps:delegation.revokedAll"));
              setConfirming(false);
            },
            onError: (error) => toast.error(getErrorMessage(error, "apps:error")),
          })
        }
      />
    </section>
  );
}

function ConnectionMembers({
  appId,
  summary,
  items,
  nameFor,
}: {
  appId: number;
  summary: AppConnectionSummary;
  items: AppMemberConnection[];
  nameFor: (userId: number) => string;
}) {
  const { t, i18n } = useTranslation(["apps", "common"]);
  const revoke = useRevokeMemberConnection(appId);
  const block = useBlockMemberConnection(appId);

  const name = localized(summary.label, i18n.language) ?? summary.connection_id;

  // Takes the translated message rather than a key, so every call site spells
  // its key as a literal and a missing one is a type error there instead of a
  // raw key surfacing in a toast.
  const notify = (message: string) => ({
    onSuccess: () => toast.success(message),
    onError: (error: unknown) => toast.error(getErrorMessage(error, "apps:error")),
  });

  const revokeMember = (item: AppMemberConnection) =>
    revoke.mutate(
      { userId: item.user_id, connectionId: item.connection_id },
      notify(t("apps:members.revoked"))
    );

  const toggleBlock = (item: AppMemberConnection) =>
    block.mutate(
      { userId: item.user_id, connectionId: item.connection_id, blocked: item.blocked },
      notify(t(item.blocked ? "apps:members.unblocked" : "apps:members.blockedDone"))
    );

  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium text-sm">{name}</h3>
        {/* The aggregate an admin actually wants, before the rows. */}
        <span className="text-muted-foreground text-xs">
          {t("apps:members.connectedCount", {
            connected: summary.connected_count,
            total: summary.member_count,
          })}
        </span>
        {summary.blocked_count > 0 && (
          <Badge variant="outline">
            {t("apps:members.blockedCount", { count: summary.blocked_count })}
          </Badge>
        )}
      </header>

      {items.length ? (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("apps:members.member")}</TableHead>
                <TableHead>{t("apps:members.account")}</TableHead>
                <TableHead>{t("apps:members.since")}</TableHead>
                <TableHead className="text-right">{t("common:actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={`${item.connection_id}-${item.user_id}`}>
                  <TableCell className="font-medium">{nameFor(item.user_id)}</TableCell>
                  <TableCell>
                    {item.blocked ? (
                      <Badge variant="destructive">{t("apps:members.blocked")}</Badge>
                    ) : (
                      (item.account_label ??
                      t(`apps:connections.status.${item.status}`, {
                        defaultValue: item.status,
                      }))
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {new Date(item.created_at).toLocaleDateString()}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      {!item.blocked && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revoke.isPending}
                          onClick={() => revokeMember(item)}
                        >
                          <UserX className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                          {t("apps:members.revoke")}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant={item.blocked ? "outline" : "destructive"}
                        disabled={block.isPending}
                        onClick={() => toggleBlock(item)}
                      >
                        <ShieldOff className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                        {item.blocked ? t("apps:members.unblock") : t("apps:members.block")}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">{t("apps:members.nobodyYet")}</p>
      )}
    </section>
  );
}
