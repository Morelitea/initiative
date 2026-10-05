/**
 * Where the community is — optional, and as broad or as exact as its admin
 * likes: a country alone, a region of one, a city, or a street address, with a
 * name of their own for the place on top. The place itself is a
 * `PlacePicker`; the street, postcode and name are this panel's own.
 */

import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateGuildApiV1CommunitiesGuildIdPatch } from "@/api/generated/communities/communities";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildLocationLine } from "@/components/guilds/GuildLocationLine";
import { PlacePicker } from "@/components/guilds/PlacePicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useGuilds } from "@/hooks/useGuilds";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import type { GuildLocation } from "@/lib/guildLocation";

/** Kept in step with the server's limits on each part. */
const LIMITS = { label: 60, address: 200, postal_code: 20 } as const;

type Draft = {
  country: string;
  region: string;
  region_code: string;
  city: string;
  address: string;
  postal_code: string;
  label: string;
};

const EMPTY_DRAFT: Draft = {
  country: "",
  region: "",
  region_code: "",
  city: "",
  address: "",
  postal_code: "",
  label: "",
};

const draftOf = (location: GuildLocation | null | undefined): Draft =>
  location
    ? {
        country: location.country,
        region: location.region ?? "",
        region_code: location.region_code ?? "",
        city: location.city ?? "",
        address: location.address ?? "",
        postal_code: location.postal_code ?? "",
        label: location.label ?? "",
      }
    : EMPTY_DRAFT;

const orNull = (value: string): string | null => value.trim() || null;

const locationOf = (draft: Draft): GuildLocation | null =>
  draft.country
    ? {
        country: draft.country,
        region: orNull(draft.region),
        region_code: orNull(draft.region_code),
        city: orNull(draft.city),
        address: orNull(draft.address),
        postal_code: orNull(draft.postal_code),
        label: orNull(draft.label),
      }
    : null;

export const GuildLocationPanel = () => {
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const { t } = useTranslation(["guilds", "common"]);
  const [draft, setDraft] = useState<Draft>(() => draftOf(activeGuild?.location));
  const [saving, setSaving] = useState(false);

  const stored = activeGuild?.location;
  // Compared by value: the guild list is refetched on focus, and a fresh copy
  // of the same location must not throw away what is being typed.
  const storedKey = JSON.stringify(stored ?? null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: storedKey is stored, by value
  useEffect(() => {
    setDraft(draftOf(stored));
  }, [storedKey]);

  if (!activeGuild) return null;

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const save = async (location: GuildLocation | null, done: string) => {
    setSaving(true);
    try {
      const result = (await updateGuildApiV1CommunitiesGuildIdPatch(activeGuild.id, {
        location,
      } as Parameters<typeof updateGuildApiV1CommunitiesGuildIdPatch>[1])) as unknown as GuildRead;
      updateGuildInState(result);
      await refreshGuilds();
      toast.success(done);
    } catch (err) {
      toast.error(getErrorMessage(err, "guilds:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void save(locationOf(draft), t("location.saved"));
  };

  const preview = locationOf(draft);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("location.title")}</CardTitle>
        <CardDescription>{t("location.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <PlacePicker value={draft} onChange={(place) => update(place)} disabled={saving} />

          {draft.country ? (
            <>
              <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
                <div className="space-y-2">
                  <Label htmlFor="guild-location-address">{t("location.addressLabel")}</Label>
                  <Input
                    id="guild-location-address"
                    value={draft.address}
                    onChange={(event) => update({ address: event.target.value })}
                    maxLength={LIMITS.address}
                    autoComplete="street-address"
                    disabled={saving}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="guild-location-postal">{t("location.postalLabel")}</Label>
                  <Input
                    id="guild-location-postal"
                    value={draft.postal_code}
                    onChange={(event) => update({ postal_code: event.target.value })}
                    maxLength={LIMITS.postal_code}
                    autoComplete="postal-code"
                    disabled={saving}
                  />
                </div>
              </div>
              <p className="-mt-2 text-muted-foreground text-xs">{t("location.addressHint")}</p>

              <div className="space-y-2">
                <Label htmlFor="guild-location-label">{t("location.labelLabel")}</Label>
                <Input
                  id="guild-location-label"
                  value={draft.label}
                  onChange={(event) => update({ label: event.target.value })}
                  maxLength={LIMITS.label}
                  placeholder={t("location.labelPlaceholder")}
                  disabled={saving}
                />
                <p className="text-muted-foreground text-xs">{t("location.labelHint")}</p>
              </div>
            </>
          ) : null}

          {preview ? (
            <div className="space-y-1 rounded-md border border-dashed p-3">
              <p className="font-medium text-muted-foreground text-xs">{t("location.preview")}</p>
              <GuildLocationLine location={preview} className="text-muted-foreground" />
            </div>
          ) : null}

          {activeGuild.is_community && preview ? (
            <p className="text-muted-foreground text-xs">{t("location.listedNote")}</p>
          ) : null}

          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={saving || !draft.country}>
              {saving ? t("settings.saving") : t("location.save")}
            </Button>
            {stored ? (
              <Button
                type="button"
                variant="outline"
                disabled={saving}
                onClick={() => void save(null, t("location.removed"))}
              >
                {t("location.remove")}
              </Button>
            ) : null}
          </div>
        </form>
      </CardContent>
    </Card>
  );
};
