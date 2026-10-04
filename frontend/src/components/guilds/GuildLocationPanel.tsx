/**
 * Where the community is — optional, and as broad or as exact as its admin
 * likes: a country alone, a region of one, a city, or a street address, with a
 * name of their own for the place on top.
 *
 * Countries, their regions and their cities come from `country-state-city`,
 * which is loaded here and nowhere else: countries and regions when the panel
 * opens, the much larger city list only once somebody opens the city field. A
 * city is a suggestion, not a requirement — a place the list does not know is
 * typed in as itself.
 */

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateGuildApiV1CommunitiesGuildIdPatch } from "@/api/generated/communities/communities";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { GuildLocationLine } from "@/components/guilds/GuildLocationLine";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { SuggestCombobox } from "@/components/ui/suggest-combobox";
import { useGuilds } from "@/hooks/useGuilds";
import { useLocationCities, useLocationPlaces } from "@/hooks/useLocationLibrary";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { countryName, type GuildLocation } from "@/lib/guildLocation";

/** Stands for "no region" in the region picker, whose values are codes. */
const NO_REGION = "__none__";
/** Cities listed at once; the rest are a search away. */
const CITY_SUGGESTION_LIMIT = 100;
/** Kept in step with the server's limits on each part. */
const LIMITS = { label: 60, city: 100, address: 200, postal_code: 20 } as const;

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
  const { t, i18n } = useTranslation(["guilds", "common"]);
  const locale = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const [draft, setDraft] = useState<Draft>(() => draftOf(activeGuild?.location));
  const [saving, setSaving] = useState(false);
  const [wantCities, setWantCities] = useState(false);

  const places = useLocationPlaces();
  const cities = useLocationCities(wantCities);

  const stored = activeGuild?.location;
  // Compared by value: the guild list is refetched on focus, and a fresh copy
  // of the same location must not throw away what is being typed.
  const storedKey = JSON.stringify(stored ?? null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: storedKey is stored, by value
  useEffect(() => {
    setDraft(draftOf(stored));
  }, [storedKey]);

  const countryItems = useMemo(
    () =>
      (places.data?.countries ?? [])
        .map((country) => ({
          value: country.isoCode,
          label: countryName(country.isoCode, locale) || country.name,
        }))
        .sort((a, b) => a.label.localeCompare(b.label, locale)),
    [places.data, locale]
  );

  const regions = useMemo(
    () => (draft.country ? (places.data?.State.getStatesOfCountry(draft.country) ?? []) : []),
    [places.data, draft.country]
  );
  const regionItems = useMemo(
    () => [
      { value: NO_REGION, label: t("location.regionNone") },
      ...regions.map((region) => ({ value: region.isoCode, label: region.name })),
    ],
    [regions, t]
  );

  const citySuggestions = useMemo(() => {
    if (!cities.data || !draft.country) return [];
    const list = draft.region_code
      ? cities.data.getCitiesOfState(draft.country, draft.region_code)
      : (cities.data.getCitiesOfCountry(draft.country) ?? []);
    return Array.from(new Set(list.map((city) => city.name)));
  }, [cities.data, draft.country, draft.region_code]);

  if (!activeGuild) return null;

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const chooseCountry = (country: string) => {
    if (country === draft.country) return;
    // A region and a city belong to the country they were picked in.
    update({ country, region: "", region_code: "", city: "" });
  };

  const chooseRegion = (code: string) => {
    if (code === NO_REGION) {
      update({ region: "", region_code: "" });
      return;
    }
    if (code === draft.region_code) return;
    const region = regions.find((candidate) => candidate.isoCode === code);
    update({ region: region?.name ?? "", region_code: code, city: "" });
  };

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
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t("location.countryLabel")}</Label>
              <SearchableCombobox
                items={countryItems}
                value={draft.country}
                onValueChange={chooseCountry}
                placeholder={
                  places.isPending ? t("location.loading") : t("location.countryPlaceholder")
                }
                emptyMessage={t("location.noMatches")}
                disabled={places.isPending || saving}
                aria-label={t("location.countryLabel")}
              />
            </div>
            {/* A country with no first-level divisions has nothing to pick. */}
            {draft.country && regions.length > 0 ? (
              <div className="space-y-2">
                <Label>{t("location.regionLabel")}</Label>
                <SearchableCombobox
                  items={regionItems}
                  value={draft.region_code || NO_REGION}
                  onValueChange={chooseRegion}
                  placeholder={t("location.regionNone")}
                  emptyMessage={t("location.noMatches")}
                  disabled={saving}
                  aria-label={t("location.regionLabel")}
                />
              </div>
            ) : null}
            {draft.country ? (
              <div className="space-y-2">
                <Label>{t("location.cityLabel")}</Label>
                <SuggestCombobox
                  suggestions={citySuggestions}
                  value={draft.city}
                  onValueChange={(city) => update({ city: city.slice(0, LIMITS.city) })}
                  placeholder={t("location.cityPlaceholder")}
                  searchPlaceholder={t("location.citySearch")}
                  loadingLabel={t("location.loading")}
                  emptyLabel={t("location.cityEmpty")}
                  typedLabel={(value) => t("location.cityTyped", { value })}
                  onOpen={() => setWantCities(true)}
                  isLoading={cities.isFetching}
                  limit={CITY_SUGGESTION_LIMIT}
                  disabled={saving}
                  aria-label={t("location.cityLabel")}
                />
              </div>
            ) : null}
          </div>

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
