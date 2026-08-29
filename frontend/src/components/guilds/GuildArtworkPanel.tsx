/**
 * The pictures a guild is known by: its icon, and its banner.
 *
 * Both are uploaded rather than typed, and both are resized here before they
 * are sent — an admin picks one file per picture and the browser produces the
 * renditions the server stores (see ``lib/guildImages``). Nobody is asked to
 * prepare a thumbnail, and nobody has to know what 4:1 means to get it right.
 *
 * A guild that would rather not go and find banner artwork picks a colour
 * instead. It is the same banner either way — the front page and the directory
 * card both render whichever is set — so the two controls sit together, and
 * the colour is what shows when there is no picture.
 *
 * Where an operator has not given a guild banner artwork, this offers the
 * colour and no upload: an upload control that only ever answers "no" is worse
 * than none. The server refuses it regardless — this is what the settings page
 * shows, not what enforces it — and a banner the guild already has keeps being
 * shown and can still be removed.
 */

import { type ChangeEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  clearGuildBannerApiV1GuildsGuildIdBannerDelete,
  clearGuildIconApiV1GuildsGuildIdIconDelete,
  setGuildBannerApiV1GuildsGuildIdBannerPut,
  setGuildIconApiV1GuildsGuildIdIconPut,
  updateGuildApiV1GuildsGuildIdPatch,
  useReadGuildEntitlementsApiV1GuildsGuildIdEntitlementsGet,
} from "@/api/generated/guilds/guilds";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { GuildImageError, renderGuildBanner, renderGuildIcon } from "@/lib/guildImages";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";

/** The colour offered before anyone has picked one. */
const DEFAULT_BANNER_COLOR = "#3f6fb5";

type Busy = "icon" | "banner" | "color" | null;

export const GuildArtworkPanel = ({ guild }: { guild: GuildRead }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const { refreshGuilds, updateGuildInState } = useGuilds();
  const [busy, setBusy] = useState<Busy>(null);
  const [color, setColor] = useState(guild.banner_color ?? DEFAULT_BANNER_COLOR);
  // Only an admin reaches this panel, which is who may read this. Until the
  // answer lands, assume artwork is on offer: it is the ordinary case, and the
  // server is what actually decides.
  const entitlements = useReadGuildEntitlementsApiV1GuildsGuildIdEntitlementsGet(guild.id);
  const mayUploadBanner = entitlements.data?.banner_image_enabled ?? true;

  useEffect(() => {
    setColor(guild.banner_color ?? DEFAULT_BANNER_COLOR);
  }, [guild.banner_color]);

  /** Every write here answers with the whole guild, so state is replaced, not patched. */
  const applied = async (updated: GuildRead) => {
    updateGuildInState(updated);
    await refreshGuilds();
  };

  const run = async (kind: Exclude<Busy, null>, work: () => Promise<GuildRead>) => {
    setBusy(kind);
    try {
      await applied(await work());
      toast.success(t("guilds:settings.artwork.saved"));
    } catch (error) {
      console.error(error);
      // A picture the browser could not make sense of never reached the
      // server, so it has its own message rather than an API code.
      toast.error(
        error instanceof GuildImageError
          ? t(`guilds:settings.artwork.${error.code}`)
          : getErrorMessage(error, "guilds:settings.artwork.failed")
      );
    } finally {
      setBusy(null);
    }
  };

  const pickIcon = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    void run("icon", async () =>
      setGuildIconApiV1GuildsGuildIdIconPut(guild.id, { icon: await renderGuildIcon(file) })
    );
  };

  const pickBanner = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    void run("banner", async () =>
      setGuildBannerApiV1GuildsGuildIdBannerPut(guild.id, await renderGuildBanner(file))
    );
  };

  const iconUrl = guild.icon_url ? resolveHeaderlessApiUrl(guild.icon_url) : null;
  const bannerUrl = guild.banner_url ? resolveHeaderlessApiUrl(guild.banner_url) : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("guilds:settings.artwork.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Label htmlFor="guild-icon">{t("guilds:settings.iconLabel")}</Label>
          <div className="flex items-center gap-4">
            {iconUrl ? (
              <img
                src={iconUrl}
                alt={t("guilds:settings.iconPreviewAlt")}
                className="h-16 w-16 rounded-lg border object-cover"
              />
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed text-muted-foreground text-xs">
                {t("guilds:settings.artwork.none")}
              </div>
            )}
            {iconUrl ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy !== null}
                onClick={() =>
                  void run("icon", () => clearGuildIconApiV1GuildsGuildIdIconDelete(guild.id))
                }
              >
                {t("guilds:settings.removeIcon")}
              </Button>
            ) : null}
          </div>
          <Input
            id="guild-icon"
            type="file"
            accept="image/*"
            disabled={busy !== null}
            onChange={pickIcon}
          />
          <p className="text-muted-foreground text-sm">{t("guilds:settings.artwork.iconHint")}</p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="guild-banner">{t("guilds:settings.artwork.bannerLabel")}</Label>
          {bannerUrl ? (
            <img
              src={bannerUrl}
              alt={t("guilds:settings.artwork.bannerPreviewAlt")}
              className="aspect-[4/1] w-full rounded-lg border object-cover"
            />
          ) : (
            <div
              className="aspect-[4/1] w-full rounded-lg border"
              style={{ backgroundColor: guild.banner_color ?? undefined }}
              aria-hidden="true"
            />
          )}
          {mayUploadBanner ? (
            <>
              <Input
                id="guild-banner"
                type="file"
                accept="image/*"
                disabled={busy !== null}
                onChange={pickBanner}
              />
              <p className="text-muted-foreground text-sm">
                {t("guilds:settings.artwork.bannerHint")}
              </p>
            </>
          ) : (
            <p className="text-muted-foreground text-sm">
              {t("guilds:settings.artwork.bannerColorOnly")}
            </p>
          )}
          {bannerUrl ? (
            <Button
              type="button"
              variant="outline"
              disabled={busy !== null}
              onClick={() =>
                void run("banner", () => clearGuildBannerApiV1GuildsGuildIdBannerDelete(guild.id))
              }
            >
              {t("guilds:settings.artwork.removeBanner")}
            </Button>
          ) : null}
        </div>

        <div className="space-y-2">
          <Label htmlFor="guild-banner-color">
            {t("guilds:settings.artwork.bannerColorLabel")}
          </Label>
          <div className="flex items-center gap-3">
            <Input
              id="guild-banner-color"
              type="color"
              value={color}
              disabled={busy !== null}
              onChange={(event) => setColor(event.target.value)}
              className="h-10 w-16 p-1"
            />
            <Button
              type="button"
              variant="outline"
              disabled={busy !== null}
              onClick={() =>
                void run("color", async () =>
                  // The endpoint answers with the whole guild; the cast is the
                  // generated client's, which types a PATCH body as unknown.
                  updateGuildApiV1GuildsGuildIdPatch(guild.id, {
                    banner_color: color,
                  } as Parameters<typeof updateGuildApiV1GuildsGuildIdPatch>[1])
                )
              }
            >
              {t("guilds:settings.artwork.useColor")}
            </Button>
            {guild.banner_color ? (
              <Button
                type="button"
                variant="ghost"
                disabled={busy !== null}
                onClick={() =>
                  void run("color", async () =>
                    updateGuildApiV1GuildsGuildIdPatch(guild.id, {
                      banner_color: null,
                    } as Parameters<typeof updateGuildApiV1GuildsGuildIdPatch>[1])
                  )
                }
              >
                {t("guilds:settings.artwork.clearColor")}
              </Button>
            ) : null}
          </div>
          <p className="text-muted-foreground text-sm">
            {t("guilds:settings.artwork.bannerColorHint")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
};
