import { Mail, Star, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import type { UserEmailRead } from "@/api/generated/initiativeAPI.schemas";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  isOnlyProvenAddress,
  useAddAddress,
  useMakeAddressPrimary,
  useMyAddresses,
  useRemoveAddress,
  visibleAddresses,
} from "@/hooks/useAddresses";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

/**
 * The addresses an account holds.
 *
 * An account has several, any proven one signs in, and account mail reaches
 * all of them — so this is a list rather than a field. The primary is the one
 * shown back to a guild.
 */
export const AddressManager = () => {
  const { t } = useTranslation(["settings", "errors"]);
  const [pending, setPending] = useState("");
  const [removeTarget, setRemoveTarget] = useState<UserEmailRead | null>(null);

  const { data, isLoading } = useMyAddresses();
  const addresses = visibleAddresses(data);

  const addAddress = useAddAddress({
    onSuccess: () => {
      setPending("");
      // One message whatever happened at the other end. Somebody may already
      // hold this address, in which case the letter went to them and nothing
      // was recorded here; the reader is told what to do next either way.
      toast.success(t("settings:addresses.checkYourMail"));
    },
    onError: (error) => toast.error(getErrorMessage(error, "settings:addresses.addFailed")),
  });

  const removeAddress = useRemoveAddress({
    onSuccess: () => {
      setRemoveTarget(null);
      toast.success(t("settings:addresses.removed"));
    },
    onError: (error) => {
      setRemoveTarget(null);
      toast.error(getErrorMessage(error, "settings:addresses.removeFailed"));
    },
  });

  const makePrimary = useMakeAddressPrimary({
    onSuccess: () => toast.success(t("settings:addresses.primaryChanged")),
    onError: (error) => toast.error(getErrorMessage(error, "settings:addresses.primaryFailed")),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const email = pending.trim();
    if (email) addAddress.mutate(email);
  };

  return (
    <div className="space-y-4">
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : (
        <ul className="space-y-2">
          {addresses.map((address) => {
            const lastProven = isOnlyProvenAddress(address, addresses);
            return (
              <li
                key={address.id}
                className="flex flex-wrap items-center gap-2 rounded-md border p-3"
              >
                <Mail className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm">{address.email}</span>
                {address.is_primary && <Badge>{t("settings:addresses.primary")}</Badge>}
                {!address.verified && (
                  <Badge variant="secondary">{t("settings:addresses.unverified")}</Badge>
                )}
                {/* Only a proven address can take account mail, so promoting an
                    unproven one is not offered. */}
                {!address.is_primary && address.verified && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => makePrimary.mutate(address.id)}
                    disabled={makePrimary.isPending}
                  >
                    <Star className="size-4" aria-hidden />
                    {t("settings:addresses.makePrimary")}
                  </Button>
                )}
                {/* The primary goes by being replaced, and the last proven
                    address does not go at all. */}
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("settings:addresses.removeLabel", {
                    email: address.email,
                  })}
                  onClick={() => setRemoveTarget(address)}
                  disabled={address.is_primary || lastProven}
                  title={
                    address.is_primary
                      ? t("settings:addresses.primaryCannotBeRemoved")
                      : lastProven
                        ? t("settings:addresses.lastCannotBeRemoved")
                        : undefined
                  }
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
      )}

      <form className="space-y-2" onSubmit={submit}>
        <Label htmlFor="new-address">{t("settings:addresses.addLabel")}</Label>
        <div className="flex flex-wrap gap-2">
          <Input
            id="new-address"
            type="email"
            className="min-w-48 flex-1"
            value={pending}
            onChange={(event) => setPending(event.target.value)}
            placeholder={t("settings:addresses.addPlaceholder")}
            autoComplete="email"
          />
          <Button type="submit" disabled={!pending.trim() || addAddress.isPending}>
            {t("settings:addresses.addAction")}
          </Button>
        </div>
        <p className="text-muted-foreground text-xs">{t("settings:addresses.addHelp")}</p>
      </form>

      <AlertDialog open={removeTarget !== null} onOpenChange={() => setRemoveTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings:addresses.removeDialogTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              <Trans
                i18nKey="addresses.removeDialogDescription"
                ns="settings"
                values={{ email: removeTarget?.email ?? "" }}
                components={{ strong: <strong /> }}
              />
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("settings:addresses.removeCancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => removeTarget && removeAddress.mutate(removeTarget.id)}
              disabled={removeAddress.isPending}
            >
              {t("settings:addresses.removeConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};
