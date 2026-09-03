import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ContactGrantRead } from "@/api/generated/initiativeAPI.schemas";
import { ContactPersonRow } from "@/components/contacts/ContactPersonRow";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  parseHandle,
  useConnections,
  useRemoveConnection,
  useRequestConnection,
} from "@/hooks/useDirectMessages";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDate } from "@/lib/formatDate";

interface ConnectionsSectionProps {
  /** Show the "connect by handle" field. Off where the page is a directory. */
  allowAdding?: boolean;
}

/**
 * Accepted connections, and the field that makes new ones.
 *
 * A connection is addressed by handle rather than picked from a list: that is
 * the only shape that reaches an account on Private, which is never offered
 * from a roster. Every target uses it, so there is no per-policy branch.
 */
export const ConnectionsSection = ({ allowAdding = true }: ConnectionsSectionProps) => {
  const { t } = useTranslation("settings");
  const { data } = useConnections();
  const requestConnection = useRequestConnection();
  const removeConnection = useRemoveConnection();
  const [handle, setHandle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const accepted: ContactGrantRead[] = data?.accepted ?? [];

  const send = () => {
    const parsed = parseHandle(handle);
    if (!parsed) {
      setError(t("privacy.connections.addHint"));
      return;
    }
    setError(null);
    requestConnection.mutate(
      { data: parsed },
      {
        onSuccess: () => {
          setHandle("");
          toast.success(t("privacy.connections.sent"));
        },
        onError: (err) => setError(getErrorMessage(err, "errors:CONTACT_GRANT_CANNOT_REACH")),
      }
    );
  };

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground text-sm">{t("privacy.connections.description")}</p>

      {allowAdding && (
        <div className="space-y-1">
          <div className="flex gap-2">
            <Input
              value={handle}
              onChange={(event) => setHandle(event.target.value)}
              placeholder={t("privacy.connections.addPlaceholder")}
              aria-label={t("privacy.connections.add")}
              onKeyDown={(event) => {
                if (event.key === "Enter") send();
              }}
            />
            <Button onClick={send} disabled={requestConnection.isPending || !handle.trim()}>
              {t("privacy.connections.send")}
            </Button>
          </div>
          <p className={error ? "text-destructive text-xs" : "text-muted-foreground text-xs"}>
            {error ?? t("privacy.connections.addHint")}
          </p>
        </div>
      )}

      {accepted.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("privacy.connections.empty")}</p>
      ) : (
        <ul className="divide-y">
          {accepted.map((connection) => (
            <ContactPersonRow
              key={connection.user_id}
              user={{ ...connection, id: connection.user_id }}
              detail={
                connection.responded_at
                  ? t("privacy.connections.connected", {
                      date: formatDate(connection.responded_at),
                    })
                  : undefined
              }
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => removeConnection.mutate({ userId: connection.user_id })}
                disabled={removeConnection.isPending}
              >
                {t("privacy.connections.remove")}
              </Button>
            </ContactPersonRow>
          ))}
        </ul>
      )}
    </div>
  );
};
