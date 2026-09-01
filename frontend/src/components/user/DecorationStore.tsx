import { Check, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DecorationPack, UserRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { ProfileAvatar } from "@/components/user/ProfileAvatar";
import { useDecorationPacks, useInstallDecorationPack } from "@/hooks/useUsers";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { type Pack, resolveDecoration, resolvePack } from "@/lib/profileDecorations";

/**
 * One pack, shown as the profile it would make.
 *
 * The card is the profile page in miniature — the banner running, the frame
 * around the reader's own face, the badge beside the name — because that is
 * the only question worth answering here: what would I look like wearing this.
 * A swatch grid could not answer it.
 */
const PackCard = ({
  pack,
  entry,
  user,
  busy,
  onInstall,
}: {
  pack: Pack;
  entry: DecorationPack;
  user: UserRead;
  busy: boolean;
  onInstall: () => void;
}) => {
  const { t } = useTranslation("profiles");
  const banner = resolveDecoration(
    entry.contents.find((item) => item.kind === "banner")?.id,
    "banner"
  );
  const frameId = entry.contents.find((item) => item.kind === "frame")?.id ?? null;
  const badge = resolveDecoration(
    entry.contents.find((item) => item.kind === "badge")?.id,
    "badge"
  );

  return (
    <li className="overflow-hidden rounded-lg border bg-card">
      <div
        className="h-24 w-full bg-center bg-cover bg-muted"
        style={banner ? { backgroundImage: `url(${banner.src})` } : undefined}
      />
      <div className="space-y-3 p-4">
        <div className="-mt-12 flex items-end gap-3">
          <ProfileAvatar
            user={user}
            decorations={{ banner: null, frame: frameId, badges: [] }}
            className="size-16 rounded-full ring-4 ring-card"
          />
          <div className="min-w-0 flex-1 pb-1">
            <div className="flex items-center gap-1.5">
              <h3 className="truncate font-semibold">{t(pack.nameKey)}</h3>
              {badge ? <img src={badge.src} alt="" aria-hidden="true" className="size-5" /> : null}
            </div>
          </div>
        </div>
        <p className="text-muted-foreground text-sm">{t(pack.taglineKey)}</p>
        {entry.installed ? (
          <p className="flex items-center gap-1.5 py-1.5 font-medium text-sm">
            <Check className="size-4" aria-hidden="true" />
            {t("store.installed")}
          </p>
        ) : (
          <Button size="sm" className="w-full" disabled={busy} onClick={onInstall}>
            {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
            {t("store.get")}
          </Button>
        )}
      </div>
    </li>
  );
};

/**
 * The decoration store.
 *
 * Every pack this build ships, for getting one. A pack already downloaded is
 * marked rather than offered again — giving one back lives with the packs you
 * have, so "get" and "give back" are never the same button in the same place.
 *
 * What a pack contains and whether you have it is the server's answer; a pack
 * this build has no artwork for is left out rather than shown as an empty card.
 */
export const DecorationStore = ({ user }: { user: UserRead }) => {
  const { t } = useTranslation(["profiles", "errors"]);
  const { data, isLoading } = useDecorationPacks();

  const onError = (error: unknown) => toast.error(getErrorMessage(error, "profiles:store.failed"));
  const install = useInstallDecorationPack({
    onSuccess: () => toast.success(t("profiles:store.got")),
    onError,
  });

  if (isLoading) {
    return (
      <div className="flex h-32 items-center justify-center">
        <Loader2 className="size-6 animate-spin text-muted-foreground" aria-hidden="true" />
      </div>
    );
  }

  const packs = (data?.items ?? [])
    .map((entry) => ({ entry, pack: resolvePack(entry.id) }))
    .filter((row): row is { entry: DecorationPack; pack: Pack } => Boolean(row.pack));

  if (packs.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("store.empty")}</p>;
  }

  return (
    <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {packs.map(({ entry, pack }) => (
        <PackCard
          key={pack.id}
          pack={pack}
          entry={entry}
          user={user}
          busy={install.isPending && install.variables === pack.id}
          onInstall={() => install.mutate(pack.id)}
        />
      ))}
    </ul>
  );
};
