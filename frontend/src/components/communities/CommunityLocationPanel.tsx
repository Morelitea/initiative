/**
 * Where the community is — optional, and as broad or as exact as its admin
 * likes: a country alone, a region of one, a city, or a street address, with a
 * name of their own for the place on top. The place itself is a
 * `PlacePicker`; the street, postcode and name are this panel's own.
 */

import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { CommunityLocationLine } from "@/components/communities/CommunityLocationLine";
import { PlacePicker } from "@/components/communities/PlacePicker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCommunities } from "@/hooks/useCommunities";
import type { CommunityLocation } from "@/lib/communityLocation";
import type { Place } from "@/lib/directoryNear";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";

/** Kept in step with the server's limits on each part. */
const LIMITS = { label: 60, address: 200, postal_code: 20 } as const;

export type Draft = {
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

const draftOf = (location: CommunityLocation | null | undefined): Draft =>
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

/**
 * A draft with a newly picked place. The street, postcode and name belong to
 * the country they were written for, as the region and city do, so a new
 * country clears them too.
 */
export const withPlace = (draft: Draft, place: Place): Draft =>
  place.country === draft.country
    ? { ...draft, ...place }
    : { ...draft, ...place, address: "", postal_code: "", label: "" };

const orNull = (value: string): string | null => value.trim() || null;

const locationOf = (draft: Draft): CommunityLocation | null =>
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

export const CommunityLocationPanel = () => {
  const { activeCommunity, refreshCommunities, updateCommunityInState } = useCommunities();
  const { t } = useTranslation(["communities", "common"]);
  const [draft, setDraft] = useState<Draft>(() => draftOf(activeCommunity?.location));
  const [saving, setSaving] = useState(false);

  const stored = activeCommunity?.location;
  // Compared by value: the community list is refetched on focus, and a fresh copy
  // of the same location must not throw away what is being typed.
  const storedKey = JSON.stringify(stored ?? null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: storedKey is stored, by value
  useEffect(() => {
    setDraft(draftOf(stored));
  }, [storedKey]);

  if (!activeCommunity) return null;

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const save = async (location: CommunityLocation | null, done: string) => {
    setSaving(true);
    try {
      const result = (await updateCommunity(activeCommunity.id, {
        location,
      } as Parameters<typeof updateCommunity>[1])) as unknown as CommunityRead;
      updateCommunityInState(result);
      await refreshCommunities();
      toast.success(done);
    } catch (err) {
      toast.error(getErrorMessage(err, "communities:settings.unableToUpdate"));
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
          <PlacePicker
            value={draft}
            onChange={(place) => setDraft((current) => withPlace(current, place))}
            disabled={saving}
          />

          {draft.country ? (
            <>
              <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
                <div className="space-y-2">
                  <Label htmlFor="community-location-address">{t("location.addressLabel")}</Label>
                  <Input
                    id="community-location-address"
                    value={draft.address}
                    onChange={(event) => update({ address: event.target.value })}
                    maxLength={LIMITS.address}
                    autoComplete="street-address"
                    disabled={saving}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="community-location-postal">{t("location.postalLabel")}</Label>
                  <Input
                    id="community-location-postal"
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
                <Label htmlFor="community-location-label">{t("location.labelLabel")}</Label>
                <Input
                  id="community-location-label"
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
              <CommunityLocationLine location={preview} className="text-muted-foreground" />
            </div>
          ) : null}

          {activeCommunity.is_community && preview ? (
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
