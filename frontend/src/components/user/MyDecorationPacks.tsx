import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DecorationPack, OwnedDecoration } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { useDecorationPacks, useRemoveDecorationPack } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import {
  type Decoration,
  type Pack,
  resolveDecoration,
  resolvePack,
} from "@/lib/profileDecorations";

/** One piece of a pack, drawn the way its slot is worn, with its slot named. */
const Piece = ({ decoration }: { decoration: Decoration }) => {
  const { t } = useTranslation("profiles");
  return (
    <li className="min-w-0">
      {decoration.kind === "banner" ? (
        <span
          className="block h-10 w-28 rounded-sm bg-center bg-cover"
          style={{ backgroundImage: `url(${decoration.src})` }}
        />
      ) : (
        <span className="flex h-10 w-28 items-center justify-start">
          <img
            src={decoration.src}
            alt=""
            aria-hidden="true"
            className={decoration.kind === "frame" ? "size-10" : "size-7"}
          />
        </span>
      )}
      <span className="mt-1 block truncate text-muted-foreground text-xs">
        {t(decoration.labelKey)}
      </span>
    </li>
  );
};

/** A pack's pieces, in slot order, skipping any this build cannot draw. */
const pieces = (contents: OwnedDecoration[]): Decoration[] =>
  (["banner", "frame", "badge"] as const)
    .map((kind) => resolveDecoration(contents.find((item) => item.kind === kind)?.id, kind))
    .filter((decoration): decoration is Decoration => Boolean(decoration));

/**
 * The packs this account has downloaded: what is in each one, and the way out.
 *
 * Separate from the store above it because they answer different questions —
 * the store is what you could have, this is what you have and what it gave you.
 * Removing lives only here, so "get" and "give back" are never the same button
 * in the same place.
 */
export const MyDecorationPacks = () => {
  const { t } = useTranslation("profiles");
  const { data, isLoading } = useDecorationPacks();
  const remove = useRemoveDecorationPack({
    onSuccess: () => toast.success(t("myPacks.removed")),
    onError: (error: unknown) => toast.error(getErrorMessage(error, "profiles:store.failed")),
  });

  if (isLoading) {
    return (
      <div className="flex h-24 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    );
  }

  const owned = (data?.items ?? [])
    .filter((entry) => entry.installed)
    .map((entry) => ({ entry, pack: resolvePack(entry.id) }))
    .filter((row): row is { entry: DecorationPack; pack: Pack } => Boolean(row.pack));

  if (owned.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("myPacks.empty")}</p>;
  }

  return (
    <ul className="divide-y rounded-lg border">
      {owned.map(({ entry, pack }) => (
        <li key={pack.id} className="flex flex-wrap items-start gap-4 p-4">
          <div className="min-w-40 flex-1">
            <h3 className="font-medium">{t(pack.nameKey)}</h3>
            <p className="text-muted-foreground text-sm">{t(pack.taglineKey)}</p>
          </div>
          <ul className="flex flex-wrap gap-4">
            {pieces(entry.contents).map((decoration) => (
              <Piece key={decoration.id} decoration={decoration} />
            ))}
          </ul>
          <Button
            variant="outline"
            size="sm"
            disabled={remove.isPending && remove.variables === pack.id}
            onClick={() => remove.mutate(pack.id)}
          >
            {t("myPacks.remove")}
          </Button>
        </li>
      ))}
    </ul>
  );
};
