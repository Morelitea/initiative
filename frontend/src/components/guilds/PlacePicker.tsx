/**
 * A place, picked: a country, and optionally its region and a city.
 *
 * The country and region lists come from `country-state-city`, loaded when the
 * picker first shows; the much larger city list only once somebody opens the
 * city field. A city is a suggestion, not a requirement — a place the list
 * does not know is typed in as itself. Used wherever somebody names a place: a
 * community saying where it is, and a newcomer saying where they are.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Label } from "@/components/ui/label";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { SuggestCombobox } from "@/components/ui/suggest-combobox";
import { useLocationCities, useLocationPlaces } from "@/hooks/useLocationLibrary";
import type { Place } from "@/lib/directoryNear";
import { countryName } from "@/lib/guildLocation";
import { cn } from "@/lib/utils";

/** Stands for "no region" in the region picker, whose values are codes. */
const NO_REGION = "__none__";
/** Cities listed at once; the rest are a search away. */
const CITY_SUGGESTION_LIMIT = 100;
/** The server's limit on a city's name. */
const CITY_MAX_LENGTH = 100;

export const PlacePicker = ({
  value,
  onChange,
  disabled = false,
  className,
}: {
  value: Place;
  onChange: (place: Place) => void;
  disabled?: boolean;
  /** The grid the fields sit in. */
  className?: string;
}) => {
  const { t, i18n } = useTranslation("guilds");
  const locale = i18n.resolvedLanguage ?? i18n.language ?? "en";
  const [wantCities, setWantCities] = useState(false);

  const places = useLocationPlaces();
  const cities = useLocationCities(wantCities);

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
    () => (value.country ? (places.data?.State.getStatesOfCountry(value.country) ?? []) : []),
    [places.data, value.country]
  );
  const regionItems = useMemo(
    () => [
      { value: NO_REGION, label: t("location.regionNone") },
      ...regions.map((region) => ({ value: region.isoCode, label: region.name })),
    ],
    [regions, t]
  );

  const citySuggestions = useMemo(() => {
    if (!cities.data || !value.country) return [];
    const list = value.region_code
      ? cities.data.getCitiesOfState(value.country, value.region_code)
      : (cities.data.getCitiesOfCountry(value.country) ?? []);
    return Array.from(new Set(list.map((city) => city.name)));
  }, [cities.data, value.country, value.region_code]);

  const chooseCountry = (country: string) => {
    if (country === value.country) return;
    // A region and a city belong to the country they were picked in.
    onChange({ country, region: "", region_code: "", city: "" });
  };

  const chooseRegion = (code: string) => {
    if (code === NO_REGION) {
      onChange({ ...value, region: "", region_code: "" });
      return;
    }
    if (code === value.region_code) return;
    const region = regions.find((candidate) => candidate.isoCode === code);
    onChange({ ...value, region: region?.name ?? "", region_code: code, city: "" });
  };

  return (
    <div className={cn("grid gap-4 sm:grid-cols-2", className)}>
      <div className="space-y-2">
        <Label>{t("location.countryLabel")}</Label>
        <SearchableCombobox
          items={countryItems}
          value={value.country}
          onValueChange={chooseCountry}
          placeholder={places.isPending ? t("location.loading") : t("location.countryPlaceholder")}
          emptyMessage={t("location.noMatches")}
          disabled={places.isPending || disabled}
          aria-label={t("location.countryLabel")}
        />
      </div>
      {/* A country with no first-level divisions has nothing to pick. */}
      {value.country && regions.length > 0 ? (
        <div className="space-y-2">
          <Label>{t("location.regionLabel")}</Label>
          <SearchableCombobox
            items={regionItems}
            value={value.region_code || NO_REGION}
            onValueChange={chooseRegion}
            placeholder={t("location.regionNone")}
            emptyMessage={t("location.noMatches")}
            disabled={disabled}
            aria-label={t("location.regionLabel")}
          />
        </div>
      ) : null}
      {value.country ? (
        <div className="space-y-2">
          <Label>{t("location.cityLabel")}</Label>
          <SuggestCombobox
            suggestions={citySuggestions}
            value={value.city}
            onValueChange={(city) => onChange({ ...value, city: city.slice(0, CITY_MAX_LENGTH) })}
            placeholder={t("location.cityPlaceholder")}
            searchPlaceholder={t("location.citySearch")}
            loadingLabel={t("location.loading")}
            emptyLabel={t("location.cityEmpty")}
            typedLabel={(typed) => t("location.cityTyped", { value: typed })}
            onOpen={() => setWantCities(true)}
            isLoading={cities.isFetching}
            limit={CITY_SUGGESTION_LIMIT}
            disabled={disabled}
            aria-label={t("location.cityLabel")}
          />
        </div>
      ) : null}
    </div>
  );
};
