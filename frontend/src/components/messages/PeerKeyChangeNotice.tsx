import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useAcknowledgeSafetyNumber,
  usePairSafetyNumber,
  usePeerKeyChanges,
} from "@/hooks/useMyMessages";

/** Five digits at a time, the way two people read a number to each other. */
const groupsOf = (digits: string) => digits.match(/.{1,5}/g) ?? [];

/**
 * The safety number with one person, both halves, and the answer that
 * releases their held devices.
 *
 * Each half belongs to one account and is laid out the same way on both
 * screens -- lower user id first -- so the comparison is the same line read
 * top to bottom on each.
 */
const SafetyNumberDialog = ({
  userId,
  nameOf,
  onClose,
}: {
  userId: number | null;
  nameOf: (userId: number) => string;
  onClose: () => void;
}) => {
  const { t } = useTranslation(["messages", "common"]);
  const number = usePairSafetyNumber(userId);
  const acknowledge = useAcknowledgeSafetyNumber();
  const name = userId === null ? "" : nameOf(userId);

  return (
    <Dialog open={userId !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("safetyNumber.title", { name })}</DialogTitle>
          <DialogDescription>{t("safetyNumber.description", { name })}</DialogDescription>
        </DialogHeader>
        {number.data ? (
          <div className="space-y-4">
            {number.data.halves.map((half) => (
              <div key={half.userId} className="space-y-1">
                <p className="text-muted-foreground text-xs">
                  {half.userId === userId ? name : t("safetyNumber.you")}
                </p>
                <p className="grid grid-cols-3 gap-x-4 gap-y-1 font-mono text-lg tabular-nums">
                  {groupsOf(half.digits).map((group, index) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: a number is a sequence, and position is the identity
                    <span key={index}>{group}</span>
                  ))}
                </p>
              </div>
            ))}
            {number.data.verified ? (
              <p className="flex items-center gap-2 text-sm">
                <ShieldCheck className="size-4 text-primary" aria-hidden />
                {t("safetyNumber.verified", { name })}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">{t("common:loading")}</p>
        )}
        <DialogFooter>
          <Button
            disabled={!number.data || userId === null || acknowledge.isPending}
            onClick={() => {
              if (!number.data || userId === null) return;
              acknowledge.mutate({ userId, number: number.data }, { onSuccess: onClose });
            }}
          >
            {t("safetyNumber.matches")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

/**
 * A conversation partner's devices changed under a thread already in use.
 *
 * This browser cannot tell on its own why, so the wording does not pretend to:
 * it leads with the ordinary reason, a replaced or reinstalled device, and says
 * the comparison is what settles it. Comparing the safety number with them and
 * saying it matches is what lets future messages use the new devices; until
 * then, sends leave them out.
 */
export const PeerKeyChangeNotice = ({
  nameOf,
}: {
  /** What to call the person a change belongs to, resolved by the page. */
  nameOf: (userId: number) => string;
}) => {
  const { t } = useTranslation("messages");
  const changes = usePeerKeyChanges();
  const [comparing, setComparing] = useState<number | null>(null);

  const change = changes.data?.[0];

  return (
    <>
      {change ? (
        <section
          className="space-y-3 border-destructive/40 border-b bg-destructive/5 px-6 py-4"
          // Announced on arrival: it appears because a send happened, not
          // because the person navigated here, so nothing else would read it.
          role="alert"
        >
          <div className="flex items-start gap-2">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            <div className="space-y-3">
              <div className="space-y-1">
                <h2 className="font-medium text-sm">
                  {t("peerKeyChange.title", { name: nameOf(change.userId) })}
                </h2>
                <p className="max-w-prose text-muted-foreground text-sm">
                  {t("peerKeyChange.body")}
                </p>
              </div>
              <Button size="sm" variant="outline" onClick={() => setComparing(change.userId)}>
                {t("peerKeyChange.compare")}
              </Button>
            </div>
          </div>
        </section>
      ) : null}
      <SafetyNumberDialog userId={comparing} nameOf={nameOf} onClose={() => setComparing(null)} />
    </>
  );
};
