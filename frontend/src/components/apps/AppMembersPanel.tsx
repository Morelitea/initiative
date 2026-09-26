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
 * Beside them, each member's answers to the app's requests to act as them,
 * which an admin can end and never give.
 *
 * Deliberately absent: the values. No admin workflow needs the bytes, and being
 * able to end someone's access is strictly more useful than being able to read
 * a token you could then use as them.
 */

import { Loader2, ShieldOff, UserX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  ConsentAccess,
  ConsentStatus,
  type GuildAppConnectionSummary,
  type GuildAppMemberConnection,
  type GuildAppMemberConsent,
} from "@/api/generated/initiativeAPI.schemas";
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
  useRevokeAllConsents,
  useRevokeMemberConnection,
  useRevokeMemberConsents,
} from "@/hooks/useGuildAppDetail";
import { useUserSearch } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { getUserDisplayName } from "@/lib/userDisplay";
import { localized } from "@/lib/widgets/widgetMeta";

export interface AppMembersPanelProps {
  appId: number;
  /** Rendered only for guild admins; the server refuses everyone else anyway. */
  enabled: boolean;
}

export function AppMembersPanel({ appId, enabled }: AppMembersPanelProps) {
  const { t } = useTranslation(["apps", "common"]);
  const [page, setPage] = useState(1);
  const membersQuery = useGuildAppMembers(appId, page, enabled);
  const summary = membersQuery.data?.summary ?? [];
  const items = membersQuery.data?.items ?? [];
  const consents = membersQuery.data?.consents ?? [];
  // Names for the members on this page only, rather than the whole roster.
  const pageUserIds = [...new Set([...items, ...consents].map((row) => row.user_id))].sort(
    (a, b) => a - b
  );
  const usersQuery = useUserSearch({
    userIds: pageUserIds,
    pageSize: Math.max(pageUserIds.length, 1),
    enabled: enabled && pageUserIds.length > 0,
  });
  const revokeAll = useRevokeAllConnections(appId);
  const [confirmingRevokeAll, setConfirmingRevokeAll] = useState(false);

  if (!enabled) return null;
  if (membersQuery.isLoading) return <Skeleton className="h-24 w-full" />;

  const consentSummary = membersQuery.data?.consent_summary;
  const totalCount = membersQuery.data?.total_count ?? 0;
  const pageSize = membersQuery.data?.page_size ?? 1;
  const pageCount = Math.max(1, Math.ceil(totalCount / pageSize));
  // The server's page, which falls back to the first when this one emptied.
  const current = membersQuery.data?.page ?? page;

  if (!summary.length && !consentSummary?.member_count) {
    return <p className="text-muted-foreground text-sm">{t("apps:members.noPersonal")}</p>;
  }

  const nameFor = (userId: number) =>
    getUserDisplayName(
      usersQuery.data?.items.find((user) => user.id === userId),
      t("apps:members.unknownMember", { id: userId })
    );

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
      {consentSummary && consentSummary.member_count > 0 && (
        <MemberConsents
          appId={appId}
          consents={consents}
          allowedCount={consentSummary.allowed_count}
          anyOpen={consentSummary.open_count > 0}
          nameFor={nameFor}
        />
      )}

      {pageCount > 1 && (
        <div className="flex items-center justify-end gap-2">
          <span className="text-muted-foreground text-sm">
            {t("common:pageOf", { current, total: pageCount })}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(current - 1)}
            disabled={!membersQuery.data?.has_prev}
          >
            {t("common:previous")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage(current + 1)}
            disabled={!membersQuery.data?.has_next}
          >
            {t("common:next")}
          </Button>
        </div>
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

/** Whether an answer still stands or still waits: the ones an admin can end. */
const isOpen = (consent: GuildAppMemberConsent) =>
  consent.status === ConsentStatus.granted || consent.status === ConsentStatus.pending;

function consentStatusKey(consent: GuildAppMemberConsent) {
  switch (consent.status) {
    case ConsentStatus.granted:
      return consent.granted_access === ConsentAccess.read_write
        ? "apps:consent.statusReadWrite"
        : "apps:consent.statusRead";
    case ConsentStatus.declined:
      return "apps:consent.statusDeclined";
    case ConsentStatus.revoked:
      return "apps:consent.statusRevoked";
    default:
      return "apps:consent.statusPending";
  }
}

/**
 * What each member answered when the app asked to act as them, one row per
 * member with every request they were asked.
 *
 * An admin ends answers and cannot give one: both buttons here revoke. Whose
 * name the app may carry is answered by that person, so an admin who takes it
 * away has taken it away — they have not moved it to a setting they control.
 */
function MemberConsents({
  appId,
  consents,
  allowedCount,
  anyOpen,
  nameFor,
}: {
  appId: number;
  /** The answers of the members on this page. */
  consents: GuildAppMemberConsent[];
  /** Across every member, not just this page. */
  allowedCount: number;
  anyOpen: boolean;
  nameFor: (userId: number) => string;
}) {
  const { t } = useTranslation(["apps", "common"]);
  const revoke = useRevokeMemberConsents(appId);
  const revokeAll = useRevokeAllConsents(appId);
  const [confirming, setConfirming] = useState(false);

  const byMember = new Map<number, GuildAppMemberConsent[]>();
  for (const consent of consents) {
    byMember.set(consent.user_id, [...(byMember.get(consent.user_id) ?? []), consent]);
  }

  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="font-medium text-sm">{t("apps:consent.membersTitle")}</h3>
        <span className="text-muted-foreground text-xs">
          {t("apps:consent.allowedCount", { count: allowedCount })}
        </span>
      </header>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("apps:members.member")}</TableHead>
              <TableHead>{t("apps:consent.requestsColumn")}</TableHead>
              <TableHead className="text-right">{t("common:actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...byMember.entries()].map(([userId, rows]) => (
              <TableRow key={userId}>
                <TableCell className="align-top font-medium">{nameFor(userId)}</TableCell>
                <TableCell>
                  <ul className="space-y-1">
                    {rows.map((row) => (
                      <li key={row.id} className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="break-words">
                          {row.purpose == null ? t("apps:consent.appWide") : row.label}
                        </span>
                        <Badge
                          variant={row.status === ConsentStatus.granted ? "secondary" : "outline"}
                        >
                          {t(consentStatusKey(row))}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </TableCell>
                <TableCell className="text-right align-top">
                  {rows.some(isOpen) && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={revoke.isPending}
                      onClick={() =>
                        revoke.mutate(userId, {
                          onSuccess: () => toast.success(t("apps:consent.memberRevoked")),
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

      {anyOpen && (
        <Button
          size="sm"
          variant="destructive"
          disabled={revokeAll.isPending}
          onClick={() => setConfirming(true)}
        >
          {revokeAll.isPending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
          {t("apps:consent.revokeAll")}
        </Button>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("apps:consent.revokeAllTitle")}
        description={t("apps:consent.revokeAllBody")}
        confirmLabel={t("apps:consent.revokeAll")}
        isLoading={revokeAll.isPending}
        destructive
        onConfirm={() =>
          revokeAll.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("apps:consent.revokedAll"));
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
  summary: GuildAppConnectionSummary;
  items: GuildAppMemberConnection[];
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

  const revokeMember = (item: GuildAppMemberConnection) =>
    revoke.mutate(
      { userId: item.user_id, connectionId: item.connection_id },
      notify(t("apps:members.revoked"))
    );

  const toggleBlock = (item: GuildAppMemberConnection) =>
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
