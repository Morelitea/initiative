/**
 * The pictures a guild is known by: its icon, and its banner.
 *
 * Both are uploaded rather than typed, and both are resized here before they
 * are sent — an admin picks one file per picture and the browser produces the
 * renditions the server stores (see ``lib/imageRenditions``). Nobody is asked to
 * prepare a thumbnail, and nobody has to know what 4:1 means to get it right.
 *
 * Every guild has a banner: the artwork it uploaded, or the colour it wears
 * instead. So there are two colours here, not one — the fill, and what the
 * guild's name and description are written in. The text colour is a setting
 * rather than something derived, because artwork is not one colour and what
 * reads over a picture is not ours to guess; picking a fill moves it to the
 * best contrast against that fill, which is the answer whenever there is no
 * artwork. It is a choice between two colours rather than a picker: black or
 * white is what keeps the words readable on a fill nobody here chose.
 *
 * Beside the two colours are the two layout choices: where the copy sits
 * across the banner, and whether the banner ends at an edge or is extended
 * past it and dissolved into the page under the page's own content. Both are
 * closed sets rather than sliders, and both save the moment they are picked —
 * there is nothing to confirm about a look the preview above is already
 * showing.
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
import {
  BannerFade,
  BannerTextAlign,
  type GuildBannerRead,
  type GuildBannerWrite,
  type GuildRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useGuilds } from "@/hooks/useGuilds";
import { renderableBanner } from "@/lib/banner";
import { toast } from "@/lib/chesterToast";
import { DARK_TEXT, LIGHT_TEXT, readableTextColor, readableTextShadow } from "@/lib/contrastColor";
import { getErrorMessage } from "@/lib/errorMessage";
import { ImageRenditionError, renderGuildBanner, renderGuildIcon } from "@/lib/imageRenditions";
import { resolveHeaderlessApiUrl } from "@/lib/uploadUrl";

type Busy = "icon" | "banner" | "look" | null;

/**
 * How much of the preview each fade eats, as a share of its height.
 *
 * The real banner fades over a fixed distance measured up from its bottom
 * edge, which is what keeps a short colour band and a tall photograph both
 * looking right. A 4:1 preview is neither of those heights, so this shows the
 * *impression* of each setting rather than its exact geometry — enough to
 * choose between them, which is what a preview is for.
 */
const PREVIEW_FADE: Record<GuildBannerRead["fade"], string | undefined> = {
  none: undefined,
  weak: "linear-gradient(to bottom, #000 65%, transparent 100%)",
  strong: "linear-gradient(to bottom, #000 15%, transparent 100%)",
};

export const GuildArtworkPanel = ({ guild }: { guild: GuildRead }) => {
  const { t } = useTranslation(["guilds", "common"]);
  const { refreshGuilds, updateGuildInState } = useGuilds();
  const [busy, setBusy] = useState<Busy>(null);
  // The banner as this panel is showing it, which is what the pickers below
  // draft against and what a save sends — the whole of it, since the endpoint
  // replaces the banner rather than merging into it.
  const [draft, setDraft] = useState(guild.banner);
  // Only an admin reaches this panel, which is who may read this. Until the
  // answer lands, assume artwork is on offer: it is the ordinary case, and the
  // server is what actually decides.
  const entitlements = useReadGuildEntitlementsApiV1GuildsGuildIdEntitlementsGet(guild.id);
  const mayUploadBanner = entitlements.data?.banner_image_enabled ?? true;

  useEffect(() => {
    setDraft(guild.banner);
  }, [guild.banner]);

  /** Show a change, without writing it — for a picker still being dragged. */
  const draftLook = (change: Partial<GuildBannerWrite>) =>
    setDraft((current) => ({ ...current, ...change }));

  /**
   * Show a change and save it. Everything here saves the moment it is picked —
   * there is nothing to confirm about a look the preview above is already
   * showing — and every save sends the whole banner, since that is what it is.
   *
   * `null` is the reset: the server puts the whole default back rather than
   * clearing anything, because a banner is never colourless and never without
   * a layout.
   */
  const commitLook = (change: Partial<GuildBannerWrite> | null) => {
    const banner = change && { ...draft, ...change };
    if (banner) setDraft(banner);
    void run("look", async () =>
      // The endpoint answers with the whole guild; the cast is the generated
      // client's, which types a PATCH body as unknown.
      updateGuildApiV1GuildsGuildIdPatch(guild.id, {
        banner,
      } as Parameters<typeof updateGuildApiV1GuildsGuildIdPatch>[1])
    );
  };

  // Picking a fill moves the text with it. Not a lock — the control stays
  // editable, and over artwork the fill is not what the words sit on anyway —
  // but it means the common case is right without anyone thinking about it.
  const withReadableText = (color: string) => ({
    color,
    text_color: readableTextColor(color),
  });

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
        error instanceof ImageRenditionError
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
  const bannerUrl = renderableBanner(guild.banner).image_url;

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
          {/* The banner as it will be: the artwork over the fill that shows
              without it, with the guild's name in the text colour on top. It
              reads from the draft colours below, so the pickers answer here
              rather than somewhere else on the page. */}
          <div
            className={`relative flex aspect-[4/1] w-full items-center overflow-hidden rounded-lg border ${
              draft.text_align === BannerTextAlign.left ? "justify-start" : "justify-center"
            }`}
          >
            {/* The ground and the fade on it, under the name rather than over
                it — the same arrangement the real banner uses, so what the
                fade does to the picture is visible and what it does to the
                words (nothing) is too. */}
            <div
              className="absolute inset-0"
              style={{
                backgroundColor: draft.color,
                maskImage: PREVIEW_FADE[draft.fade],
                WebkitMaskImage: PREVIEW_FADE[draft.fade],
              }}
            >
              {bannerUrl ? (
                <img
                  src={bannerUrl}
                  alt={t("guilds:settings.artwork.bannerPreviewAlt")}
                  className="h-full w-full object-cover"
                />
              ) : null}
            </div>
            <span
              className="relative truncate px-4 font-black text-lg sm:text-2xl"
              style={{ color: draft.text_color, textShadow: readableTextShadow(draft.text_color) }}
            >
              {guild.name}
            </span>
          </div>
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
          <div className="flex flex-wrap items-end gap-6">
            <div className="space-y-2">
              <Label htmlFor="guild-banner-color">
                {t("guilds:settings.artwork.bannerColorLabel")}
              </Label>
              <ColorPickerPopover
                id="guild-banner-color"
                value={draft.color}
                disabled={busy !== null}
                onChange={(next) => draftLook(withReadableText(next))}
                onChangeComplete={(next) => commitLook(withReadableText(next))}
                triggerLabel={t("guilds:settings.artwork.bannerColorLabel")}
              />
            </div>
            <fieldset className="space-y-2" disabled={busy !== null}>
              <legend className="pb-2 font-medium text-sm">
                {t("guilds:settings.artwork.bannerTextColorLabel")}
              </legend>
              <div className="flex gap-2">
                {[
                  { value: LIGHT_TEXT, label: t("guilds:settings.artwork.textLight") },
                  { value: DARK_TEXT, label: t("guilds:settings.artwork.textDark") },
                ].map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant={draft.text_color === option.value ? "default" : "outline"}
                    aria-pressed={draft.text_color === option.value}
                    onClick={() => commitLook({ text_color: option.value })}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </fieldset>
            <fieldset className="space-y-2" disabled={busy !== null}>
              <legend className="pb-2 font-medium text-sm">
                {t("guilds:settings.artwork.bannerAlignLabel")}
              </legend>
              <div className="flex gap-2">
                {[
                  {
                    value: BannerTextAlign.center,
                    label: t("guilds:settings.artwork.alignCenter"),
                  },
                  { value: BannerTextAlign.left, label: t("guilds:settings.artwork.alignLeft") },
                ].map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant={draft.text_align === option.value ? "default" : "outline"}
                    aria-pressed={draft.text_align === option.value}
                    onClick={() => commitLook({ text_align: option.value })}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </fieldset>
            <fieldset className="space-y-2" disabled={busy !== null}>
              <legend className="pb-2 font-medium text-sm">
                {t("guilds:settings.artwork.bannerFadeLabel")}
              </legend>
              <div className="flex gap-2">
                {[
                  { value: BannerFade.none, label: t("guilds:settings.artwork.fadeNone") },
                  { value: BannerFade.weak, label: t("guilds:settings.artwork.fadeWeak") },
                  { value: BannerFade.strong, label: t("guilds:settings.artwork.fadeStrong") },
                ].map((option) => (
                  <Button
                    key={option.value}
                    type="button"
                    size="sm"
                    variant={draft.fade === option.value ? "default" : "outline"}
                    aria-pressed={draft.fade === option.value}
                    onClick={() => commitLook({ fade: option.value })}
                  >
                    {option.label}
                  </Button>
                ))}
              </div>
            </fieldset>
          </div>
          <p className="text-muted-foreground text-sm">
            {t("guilds:settings.artwork.bannerFadeHint")}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={busy !== null}
            onClick={() => commitLook(null)}
          >
            {t("guilds:settings.artwork.resetColor")}
          </Button>
          <p className="text-muted-foreground text-sm">
            {t("guilds:settings.artwork.bannerColorHint")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
};
