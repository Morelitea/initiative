import { MoreHorizontal } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  useConnections,
  useDmPermission,
  useIgnoreAccount,
  useIgnoredAccounts,
  useRemoveConnection,
  useRequestConnection,
  useRequestMessage,
  useStopIgnoring,
} from "@/hooks/useDirectMessages";
import { toast } from "@/lib/chesterToast";

interface ContactActionsMenuProps {
  /** The account being acted on. The handle is what a connection is addressed
   *  by, so both halves of it are needed, not just the id. */
  user: { id: number; username: string; discriminator: number };
  /** Rendered inside a link or a row that is itself clickable. */
  className?: string;
}

/**
 * What one person can do about another, wherever they meet them.
 *
 * Until this existed the writes had no caller: ignoring was reachable only by
 * already knowing somebody's exact handle and opening Settings, which is the
 * opposite of the moment somebody reaches for it. So the menu goes where the
 * person is — their profile, and their row on My Contacts.
 *
 * Which items appear is read from ``dm_permission``, one collapsed value the
 * server computes. *Ask to message* on ``may_request``, nothing on ``denied``
 * — and because every refusal collapses into that one word, a menu built from
 * it says nothing about which refusal it is.
 */
export const ContactActionsMenu = ({ user, className }: ContactActionsMenuProps) => {
  const { t } = useTranslation(["contacts", "settings"]);
  const [confirmingRemove, setConfirmingRemove] = useState(false);

  const { data: permission } = useDmPermission(user.id);
  const { data: connections } = useConnections();
  const { data: ignored } = useIgnoredAccounts();

  const requestConnection = useRequestConnection();
  const requestMessage = useRequestMessage();
  const removeConnection = useRemoveConnection();
  const ignore = useIgnoreAccount();
  const stopIgnoring = useStopIgnoring();

  const isConnection = (connections?.accepted ?? []).some((g) => g.user_id === user.id);
  const isPending = (connections?.incoming ?? [])
    .concat(connections?.outgoing ?? [])
    .some((g) => g.user_id === user.id);
  const isIgnored = (ignored?.items ?? []).some((row) => row.user_id === user.id);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={className}
            aria-label={t("actions.label", { handle: user.username })}
          >
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {!isConnection && !isPending && (
            <DropdownMenuItem
              onSelect={() =>
                requestConnection.mutate(
                  { data: { username: user.username, discriminator: user.discriminator } },
                  { onSuccess: () => toast.success(t("settings:privacy.connections.sent")) }
                )
              }
            >
              {t("actions.connect")}
            </DropdownMenuItem>
          )}
          {permission?.permission === "may_request" && (
            <DropdownMenuItem
              onSelect={() =>
                requestMessage.mutate(
                  { data: { user_id: user.id } },
                  { onSuccess: () => toast.success(t("actions.askSent")) }
                )
              }
            >
              {t("actions.ask")}
            </DropdownMenuItem>
          )}
          {isConnection && (
            <DropdownMenuItem onSelect={() => setConfirmingRemove(true)}>
              {t("actions.removeConnection")}
            </DropdownMenuItem>
          )}
          {isIgnored ? (
            <DropdownMenuItem onSelect={() => stopIgnoring.mutate({ userId: user.id })}>
              {t("actions.stopIgnoring")}
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem
              onSelect={() => ignore.mutate({ userId: user.id })}
              className="text-destructive"
            >
              {t("actions.ignore")}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Removing a connection can take the open channel with it, and whether
          it does depends on the other account's own policy — which is theirs,
          not something to read off this dialog. So it says what is certain and
          does not guess which case this pair is. */}
      <ConfirmDialog
        open={confirmingRemove}
        onOpenChange={setConfirmingRemove}
        title={t("actions.removeConnectionTitle")}
        description={t("actions.removeConnectionBody")}
        confirmLabel={t("actions.removeConnection")}
        destructive
        isLoading={removeConnection.isPending}
        onConfirm={() =>
          removeConnection.mutate(
            { userId: user.id },
            { onSuccess: () => setConfirmingRemove(false) }
          )
        }
      />
    </>
  );
};
