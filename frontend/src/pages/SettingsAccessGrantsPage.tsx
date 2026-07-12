import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AccessGrantRead,
  AccessGrantStatus,
  UserRole,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  flattenGrants,
  useAccessGrantQueue,
  useApproveAccessGrant,
  useBreakGlass,
  useCancelAccessRequest,
  useCreateAccessRequest,
  useDenyAccessGrant,
  useMyAccessGrants,
  useRevokeAccessGrant,
} from "@/hooks/useAccessGrants";
import { useAuth } from "@/hooks/useAuth";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { Capability, hasCapability } from "@/lib/permissions";

const STATUS_VARIANT: Record<
  AccessGrantStatus,
  "default" | "secondary" | "outline" | "destructive"
> = {
  pending: "secondary",
  approved: "default",
  denied: "destructive",
  revoked: "destructive",
  expired: "outline",
};

const minutesLeft = (expiresAt?: string | null): number | null => {
  if (!expiresAt) return null;
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 60000));
};

// Always surface the guild id alongside the name so approvers can
// disambiguate similarly-named guilds (and fall back cleanly when the name
// isn't populated).
const guildLabel = (grant: { guild_name?: string | null; guild_id: number }): string =>
  grant.guild_name ? `${grant.guild_name} (#${grant.guild_id})` : `#${grant.guild_id}`;

// Float the actionable grants to the top so they're never buried under dead
// history: pending (you can cancel) first, then live (currently usable), then
// everything else. Stable over the backend's newest-first ordering.
const activityRank = (grant: AccessGrantRead): number => {
  if (grant.status === "pending") return 0;
  if (grant.is_live) return 1;
  return 2;
};

// Least-privilege grant-duration caps per requester role. MUST match the
// backend PAM_*_MAX_MINUTES defaults — the backend enforces; this only
// decides which presets to offer. (member can't request.)
const ROLE_MAX_MINUTES: Partial<Record<UserRole, number>> = {
  support: 240, // 4h
  moderator: 480, // 8h
  operator: 1440, // 24h
  owner: 1440,
};

// All whole-hour presets, ascending.
const DURATION_PRESETS_MINUTES = [60, 240, 480, 1440];

const allowedDurations = (role: UserRole | undefined): number[] => {
  const max = (role && ROLE_MAX_MINUTES[role]) ?? 240;
  return DURATION_PRESETS_MINUTES.filter((m) => m <= max);
};

export const SettingsAccessGrantsPage = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const canRequest = hasCapability(user, Capability.accessRequest);
  const canApprove = hasCapability(user, Capability.accessApprove);
  const canBreakGlass = hasCapability(user, Capability.dataBypass);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-semibold text-2xl tracking-tight">{t("accessGrants.title")}</h2>
        <p className="text-muted-foreground">{t("accessGrants.description")}</p>
      </div>
      {canApprove && <ApprovalQueue />}
      {canBreakGlass && <BreakGlassSection />}
      {canRequest && <RequestSection />}
    </div>
  );
};

const LoadMore = ({
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  if (!hasNextPage) return null;
  return (
    <div className="flex justify-center pt-1">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onLoadMore}
        disabled={isFetchingNextPage}
      >
        {isFetchingNextPage ? t("common:loading") : t("accessGrants.loadMore")}
      </Button>
    </div>
  );
};

const StatusBadge = ({ grant }: { grant: AccessGrantRead }) => {
  const { t } = useTranslation("settings");
  return (
    <Badge variant={STATUS_VARIANT[grant.status]}>{t(`accessGrants.status.${grant.status}`)}</Badge>
  );
};

// Break-glass duration presets (whole hours), capped at the backend's
// PAM_BREAK_GLASS_MAX_MINUTES (4h) — a self-approved grant is deliberately short.
const BREAK_GLASS_DURATIONS_MINUTES = [60, 120, 240];

// Self-serve emergency access for data.bypass holders (operator/owner). Unlike a
// request, this is approved on creation — live immediately, scoped to one guild,
// read-only by default, short-lived, and recorded as an audited grant.
const BreakGlassSection = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { refreshGuilds } = useGuilds();
  const [guildId, setGuildId] = useState("");
  const [level, setLevel] = useState("read");
  const [duration, setDuration] = useState("60");
  const [reason, setReason] = useState("");

  const breakGlass = useBreakGlass({
    onSuccess: () => {
      toast.success(t("accessGrants.breakGlass.activated"));
      setGuildId("");
      setReason("");
      setLevel("read");
      setDuration("60");
      // A break-glass grant is live immediately. The guild switcher and the
      // /g/{id} route guard read from the GuildProvider's context list (not
      // React Query), so refresh it here — otherwise the newly-reachable guild
      // doesn't appear until a manual reload.
      void refreshGuilds();
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.breakGlass.error")),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const gid = Number.parseInt(guildId, 10);
    if (!gid || !reason.trim()) return;
    breakGlass.mutate({
      guild_id: gid,
      access_level: level as "read" | "read_write",
      reason: reason.trim(),
      requested_duration_minutes: Number.parseInt(duration, 10),
    });
  };

  return (
    <Card className="border-destructive/40 shadow-sm">
      <CardHeader>
        <CardTitle>{t("accessGrants.breakGlass.title")}</CardTitle>
        <CardDescription>{t("accessGrants.breakGlass.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          <div className="space-y-1">
            <Label htmlFor="bg-guild">{t("accessGrants.guildIdLabel")}</Label>
            <Input
              id="bg-guild"
              type="number"
              value={guildId}
              onChange={(e) => setGuildId(e.target.value)}
              placeholder={t("accessGrants.guildIdPlaceholder")}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="bg-level">{t("accessGrants.levelLabel")}</Label>
            <Select value={level} onValueChange={setLevel}>
              <SelectTrigger id="bg-level">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("accessGrants.levelRead")}</SelectItem>
                <SelectItem value="read_write">{t("accessGrants.levelReadWrite")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="bg-duration">{t("accessGrants.durationLabel")}</Label>
            <Select value={duration} onValueChange={setDuration}>
              <SelectTrigger id="bg-duration">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {BREAK_GLASS_DURATIONS_MINUTES.map((minutes) => (
                  <SelectItem key={minutes} value={String(minutes)}>
                    {t("accessGrants.durationHours", { count: minutes / 60 })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="bg-reason">{t("accessGrants.reasonLabel")}</Label>
            <Textarea
              id="bg-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t("accessGrants.breakGlass.reasonPlaceholder")}
              required
            />
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" variant="destructive" disabled={breakGlass.isPending}>
              {breakGlass.isPending ? t("common:submitting") : t("accessGrants.breakGlass.submit")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
};

const RequestSection = () => {
  const { t } = useTranslation(["settings", "common"]);
  const { user } = useAuth();
  const myGrants = useMyAccessGrants();
  const sortedGrants = useMemo(
    () => flattenGrants(myGrants.data?.pages).sort((a, b) => activityRank(a) - activityRank(b)),
    [myGrants.data]
  );
  const durationOptions = allowedDurations(user?.role);
  const defaultDuration = String(durationOptions.includes(240) ? 240 : (durationOptions[0] ?? 240));
  const [guildId, setGuildId] = useState("");
  const [level, setLevel] = useState("read");
  const [duration, setDuration] = useState(defaultDuration);
  const [reason, setReason] = useState("");

  const createRequest = useCreateAccessRequest({
    onSuccess: () => {
      toast.success(t("accessGrants.requestSubmitted"));
      setGuildId("");
      setReason("");
      setDuration(defaultDuration);
    },
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.requestError")),
  });
  const cancelRequest = useCancelAccessRequest({
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.cancelError")),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const gid = Number.parseInt(guildId, 10);
    if (!gid || !reason.trim()) return;
    createRequest.mutate({
      guild_id: gid,
      access_level: level as "read" | "read_write",
      reason: reason.trim(),
      requested_duration_minutes: Number.parseInt(duration, 10),
    });
  };

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("accessGrants.requestTitle")}</CardTitle>
        <CardDescription>{t("accessGrants.requestDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          <div className="space-y-1">
            <Label htmlFor="ag-guild">{t("accessGrants.guildIdLabel")}</Label>
            <Input
              id="ag-guild"
              type="number"
              value={guildId}
              onChange={(e) => setGuildId(e.target.value)}
              placeholder={t("accessGrants.guildIdPlaceholder")}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="ag-level">{t("accessGrants.levelLabel")}</Label>
            <Select value={level} onValueChange={setLevel}>
              <SelectTrigger id="ag-level">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("accessGrants.levelRead")}</SelectItem>
                <SelectItem value="read_write">{t("accessGrants.levelReadWrite")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="ag-duration">{t("accessGrants.durationLabel")}</Label>
            <Select value={duration} onValueChange={setDuration}>
              <SelectTrigger id="ag-duration">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {durationOptions.map((minutes) => (
                  <SelectItem key={minutes} value={String(minutes)}>
                    {t("accessGrants.durationHours", { count: minutes / 60 })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1 sm:col-span-2">
            <Label htmlFor="ag-reason">{t("accessGrants.reasonLabel")}</Label>
            <Textarea
              id="ag-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t("accessGrants.reasonPlaceholder")}
              required
            />
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={createRequest.isPending}>
              {createRequest.isPending ? t("common:submitting") : t("accessGrants.submitRequest")}
            </Button>
          </div>
        </form>

        <div className="space-y-2">
          <h3 className="font-medium text-sm">{t("accessGrants.myRequests")}</h3>
          {!sortedGrants.length ? (
            <p className="text-muted-foreground text-sm">{t("accessGrants.noRequests")}</p>
          ) : (
            <ul className="divide-y rounded-md border">
              {sortedGrants.map((grant) => {
                const left = minutesLeft(grant.expires_at);
                return (
                  <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm">
                        {guildLabel(grant)} · {grant.access_level}
                      </p>
                      <p className="truncate text-muted-foreground text-xs">{grant.reason}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {grant.is_live && left !== null && (
                        <span className="text-muted-foreground text-xs">
                          {t("accessGrants.expiresIn", { minutes: left })}
                        </span>
                      )}
                      <StatusBadge grant={grant} />
                      {grant.status === "pending" && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => cancelRequest.mutate(grant.id)}
                          disabled={cancelRequest.isPending}
                        >
                          {t("common:cancel")}
                        </Button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <LoadMore
            hasNextPage={myGrants.hasNextPage}
            isFetchingNextPage={myGrants.isFetchingNextPage}
            onLoadMore={() => myGrants.fetchNextPage()}
          />
        </div>
      </CardContent>
    </Card>
  );
};

const ApprovalQueue = () => {
  const { t } = useTranslation(["settings", "common"]);
  const pending = useAccessGrantQueue("pending");
  // Server-side ``live`` filter so paging the active list is accurate (no
  // client-side is_live filtering that would leave pages partially empty).
  const active = useAccessGrantQueue("approved", { live: true });
  const pendingItems = flattenGrants(pending.data?.pages);
  const activeItems = flattenGrants(active.data?.pages);

  const approve = useApproveAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.approved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.actionError")),
  });
  const deny = useDenyAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.denied")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.actionError")),
  });
  const revoke = useRevokeAccessGrant({
    onSuccess: () => toast.success(t("accessGrants.revoked")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:accessGrants.actionError")),
  });

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle>{t("accessGrants.queueTitle")}</CardTitle>
        <CardDescription>{t("accessGrants.queueDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2">
          <h3 className="font-medium text-sm">{t("accessGrants.pendingHeading")}</h3>
          {!pendingItems.length ? (
            <p className="text-muted-foreground text-sm">{t("accessGrants.noPending")}</p>
          ) : (
            <ul className="divide-y rounded-md border">
              {pendingItems.map((grant) => (
                <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">
                      {grant.user_email ?? `user #${grant.user_id}`} → {guildLabel(grant)} ·{" "}
                      {grant.access_level} ·{" "}
                      {t("accessGrants.minutes", { minutes: grant.requested_duration_minutes })}
                    </p>
                    <p className="truncate text-muted-foreground text-xs">{grant.reason}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => approve.mutate({ grantId: grant.id })}
                      disabled={approve.isPending}
                    >
                      {t("accessGrants.approve")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => deny.mutate(grant.id)}
                      disabled={deny.isPending}
                    >
                      {t("accessGrants.deny")}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <LoadMore
            hasNextPage={pending.hasNextPage}
            isFetchingNextPage={pending.isFetchingNextPage}
            onLoadMore={() => pending.fetchNextPage()}
          />
        </div>

        <div className="space-y-2">
          <h3 className="font-medium text-sm">{t("accessGrants.activeHeading")}</h3>
          {!activeItems.length ? (
            <p className="text-muted-foreground text-sm">{t("accessGrants.noActive")}</p>
          ) : (
            <ul className="divide-y rounded-md border">
              {activeItems.map((grant) => {
                const left = minutesLeft(grant.expires_at);
                return (
                  <li key={grant.id} className="flex items-center justify-between gap-3 p-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm">
                        {grant.user_email ?? `user #${grant.user_id}`} → {guildLabel(grant)} ·{" "}
                        {grant.access_level}
                      </p>
                      {left !== null && (
                        <p className="text-muted-foreground text-xs">
                          {t("accessGrants.expiresIn", { minutes: left })}
                        </p>
                      )}
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => revoke.mutate(grant.id)}
                      disabled={revoke.isPending}
                    >
                      {t("accessGrants.revoke")}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
          <LoadMore
            hasNextPage={active.hasNextPage}
            isFetchingNextPage={active.isFetchingNextPage}
            onLoadMore={() => active.fetchNextPage()}
          />
        </div>
      </CardContent>
    </Card>
  );
};
