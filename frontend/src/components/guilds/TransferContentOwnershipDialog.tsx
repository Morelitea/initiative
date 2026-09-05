import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  OwnedContentResponse,
  OwnershipTransferResponse,
  Tool,
  UserGuildMember,
} from "@/api/generated/initiativeAPI.schemas";
import {
  claimUnownedContentApiV1GGuildIdUsersUnownedContentClaimPost,
  listOwnedContentApiV1GGuildIdUsersUserIdOwnedContentGet,
  listUnownedContentApiV1GGuildIdUsersUnownedContentGet,
  transferOwnershipApiV1GGuildIdUsersUserIdTransferOwnershipPost,
} from "@/api/generated/users/users";
import { invalidateGuildMembers } from "@/api/query-keys";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { toolCamelPlural } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";

/**
 * Counts keyed by tool, rendered as "3 projects · 1 calendar". The label comes
 * from the tool's own nav string, so a new tool needs nothing here.
 */
const useToolCounts = (counts: Record<string, number> | undefined) => {
  const { t } = useTranslation(["nav"]);
  return useMemo(
    () =>
      Object.entries(counts ?? {}).map(([tool, count]) => ({
        tool,
        count,
        label: t(`nav:${toolCamelPlural(tool as Tool)}` as never),
      })),
    [counts, t]
  );
};

interface TransferContentOwnershipDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whose content moves. Null claims everything nobody owns instead. */
  member: UserGuildMember | null;
  /** Guild admins eligible to receive it. */
  admins: UserGuildMember[];
  /** Pre-selected recipient — the acting admin. */
  defaultRecipientId?: number;
  onSuccess?: () => void;
}

/**
 * Moves everything a member owns in this guild to a guild admin, and the only
 * place in the app that does. Recipients are limited to guild admins, who
 * already reach every part of the guild, so a transfer can never widen anyone's
 * access.
 *
 * With `member` null it claims the guild's unowned content instead — the pile
 * that accumulates as people leave, since departures release ownership rather
 * than handing it on.
 */
export const TransferContentOwnershipDialog = ({
  open,
  onOpenChange,
  member,
  admins,
  defaultRecipientId,
  onSuccess,
}: TransferContentOwnershipDialogProps) => {
  const { t } = useTranslation(["guilds", "common"]);
  const guildId = useActiveGuildId();
  const [recipientId, setRecipientId] = useState<string>(defaultRecipientId?.toString() ?? "");
  const [content, setContent] = useState<OwnedContentResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const isClaim = member === null;

  const memberId = member?.id ?? null;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setContent(null);
    setLoading(true);
    setRecipientId(defaultRecipientId?.toString() ?? "");

    const load = async () => {
      try {
        const data = (memberId === null
          ? await listUnownedContentApiV1GGuildIdUsersUnownedContentGet(guildId)
          : await listOwnedContentApiV1GGuildIdUsersUserIdOwnedContentGet(
              guildId,
              memberId
            )) as unknown as OwnedContentResponse;
        if (!cancelled) setContent(data);
      } catch (err) {
        console.error("Failed to load owned content", err);
        if (!cancelled) toast.error(getErrorMessage(err, "guilds:transferOwnership.loadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [open, memberId, guildId, defaultRecipientId]);

  const toolCounts = useToolCounts(content?.counts);
  const nothingToMove = !loading && (content?.total ?? 0) === 0;

  const handleSubmit = async () => {
    if (!recipientId) return;
    setSubmitting(true);
    try {
      const body = { new_owner_id: Number(recipientId) };
      const result = (member === null
        ? await claimUnownedContentApiV1GGuildIdUsersUnownedContentClaimPost(guildId, body)
        : await transferOwnershipApiV1GGuildIdUsersUserIdTransferOwnershipPost(
            guildId,
            member.id,
            body
          )) as unknown as OwnershipTransferResponse;
      void invalidateGuildMembers();
      toast.success(t("transferOwnership.moved", { count: result.total }));
      onSuccess?.();
      onOpenChange(false);
    } catch (err) {
      console.error("Failed to transfer ownership", err);
      toast.error(getErrorMessage(err, "guilds:transferOwnership.failed"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {isClaim ? t("transferOwnership.claimTitle") : t("transferOwnership.title")}
          </DialogTitle>
          <DialogDescription>
            {isClaim
              ? t("transferOwnership.claimDescription")
              : t("transferOwnership.description", {
                  name: member ? getUserDisplayName(member) : "",
                })}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : nothingToMove ? (
          <p className="text-muted-foreground text-sm">
            {isClaim ? t("transferOwnership.nothingUnowned") : t("transferOwnership.nothingOwned")}
          </p>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2 rounded-md border p-3">
              <p className="font-medium text-sm">{t("transferOwnership.whatMoves")}</p>
              <ul className="space-y-1">
                {toolCounts.map(({ tool, count, label }) => (
                  <li key={tool} className="text-muted-foreground text-sm">
                    {count} × {label}
                  </li>
                ))}
              </ul>
            </div>

            <div className="space-y-2">
              <Label htmlFor="transfer-recipient">{t("transferOwnership.recipientLabel")}</Label>
              <Select value={recipientId} onValueChange={setRecipientId}>
                <SelectTrigger id="transfer-recipient">
                  <SelectValue placeholder={t("transferOwnership.recipientPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {admins.map((admin) => (
                    <SelectItem key={admin.id} value={admin.id.toString()}>
                      {getUserDisplayName(admin)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("transferOwnership.adminsOnly")}</p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            {t("common:cancel")}
          </Button>
          {!nothingToMove && !loading && (
            <Button onClick={handleSubmit} disabled={submitting || !recipientId}>
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {t("transferOwnership.transferring")}
                </>
              ) : (
                t("transferOwnership.confirm")
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
