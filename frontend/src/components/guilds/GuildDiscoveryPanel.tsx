/**
 * The community-directory opt-in, on the guild settings page.
 *
 * Guild admins only — the API refuses these fields from anyone else, and the
 * whole settings section is admin-gated — so the panel is simply absent for a
 * member rather than shown disabled. Absent too where the platform owner runs
 * no directory: there would be nothing to list in.
 *
 * Saved on its own rather than folded into the details form above: listing a
 * guild publishes it to everyone signed in, which is a different decision from
 * renaming it, and the PATCH treats omitted fields as untouched so the two
 * never overwrite each other.
 *
 * Three conditions gate a listing, and the server enforces all three (two of
 * them as database CHECKs). What the UI adds is that they are asked *before*
 * the request rather than reported after it: the publish dialog collects the
 * categories and the content certification together, and a guild whose seat
 * limit leaves no room to join is told so instead of being offered a toggle
 * that can only fail.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateGuildApiV1GuildsGuildIdPatch } from "@/api/generated/guilds/guilds";
import type { GuildCategory, GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useGuilds } from "@/hooks/useGuilds";
import { getErrorMessage } from "@/lib/errorMessage";
import { GUILD_CATEGORIES, guildCategoryLabel } from "@/lib/guildCategories";
import { cn } from "@/lib/utils";

import { PublishGuildDialog } from "./PublishGuildDialog";

/** A guild with one seat can never admit a joiner, so it is never listed.
 *  Mirrors MIN_COMMUNITY_SEATS on the server, which is what enforces it. */
const MIN_COMMUNITY_SEATS = 2;

export const GuildDiscoveryPanel = () => {
  const { t } = useTranslation(["guilds", "common"]);
  const { activeGuild, refreshGuilds, updateGuildInState } = useGuilds();
  const { communityDirectoryEnabled } = useAppConfig();
  const [publishing, setPublishing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMessage(null);
    setError(null);
  }, [activeGuild]);

  if (!communityDirectoryEnabled || activeGuild?.role !== "admin") {
    return null;
  }

  const listed = activeGuild.is_community;
  const isAdult = activeGuild.has_adult_content === true;
  // null is unlimited. Only an operator sets this, so an admin who hits it is
  // told who to ask rather than offered a control they cannot satisfy.
  const seatLimited = activeGuild.max_users != null && activeGuild.max_users < MIN_COMMUNITY_SEATS;
  const canList = !isAdult && !seatLimited;

  const save = async (updates: Partial<GuildRead>) => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = (await updateGuildApiV1GuildsGuildIdPatch(
        activeGuild.id,
        updates as Parameters<typeof updateGuildApiV1GuildsGuildIdPatch>[1]
      )) as unknown as GuildRead;
      updateGuildInState(result);
      await refreshGuilds();
      setMessage(t("guilds:settings.updatedSuccessfully"));
      return true;
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, "guilds:settings.unableToUpdate"));
      return false;
    } finally {
      setSaving(false);
    }
  };

  // Listing is a publication, so it goes through the dialog that collects the
  // categories and the certification. Un-listing publishes nothing and asks
  // nothing — it takes effect on the click.
  const handleToggle = (next: boolean) => {
    if (next) {
      setPublishing(true);
      return;
    }
    void save({ is_community: false });
  };

  const toggleCategory = (category: GuildCategory) => {
    const next = activeGuild.categories.includes(category)
      ? activeGuild.categories.filter((value) => value !== category)
      : [...activeGuild.categories, category];
    void save({ categories: next });
  };

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("guilds:settings.discoveryTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            {t("guilds:settings.discoveryDescription")}
          </p>

          <div className="flex items-center gap-3">
            <Switch
              id="guild-is-community"
              checked={listed}
              disabled={saving || (!listed && !canList)}
              onCheckedChange={handleToggle}
            />
            <Label htmlFor="guild-is-community">{t("guilds:settings.discoveryToggleLabel")}</Label>
          </div>

          {/* Why the toggle is unavailable, rather than an inert control. */}
          {!listed && seatLimited ? (
            <p className="text-muted-foreground text-sm">
              {t("guilds:settings.discoveryCapacityBlocked")}
            </p>
          ) : null}
          {!listed && isAdult && !seatLimited ? (
            <p className="text-muted-foreground text-sm">
              {t("guilds:settings.discoveryAdultHint")}
            </p>
          ) : null}

          {/* The shelves only matter once the guild is on one. They are editable
              here afterwards; the dialog is only for the first publication. */}
          {listed ? (
            <fieldset className="space-y-2">
              <legend className="font-medium text-sm">
                {t("guilds:settings.discoveryCategoriesLabel")}
              </legend>
              <p className="text-muted-foreground text-sm">
                {t("guilds:settings.discoveryCategoriesHint")}
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                {GUILD_CATEGORIES.map((category) => {
                  const selected = activeGuild.categories.includes(category);
                  return (
                    <button
                      key={category}
                      type="button"
                      onClick={() => toggleCategory(category)}
                      aria-pressed={selected}
                      disabled={saving}
                      className={cn(
                        "rounded-full border px-3 py-1 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                        selected
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-input text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      {guildCategoryLabel(category, t)}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ) : null}

          {/* The 18+ declaration. Its own decision, and one a guild that never
              lists itself is free to make either way — but a listed guild has
              already certified the opposite, so it is de-list-first. */}
          <div className="space-y-2 border-t pt-4">
            <div className="flex items-center gap-3">
              <Switch
                id="guild-has-adult-content"
                checked={isAdult}
                disabled={saving || listed}
                onCheckedChange={(next) => void save({ has_adult_content: next })}
              />
              <Label htmlFor="guild-has-adult-content">
                {t("guilds:settings.discoveryAdultLabel")}
              </Label>
            </div>
            <p className="text-muted-foreground text-sm">
              {listed
                ? t("guilds:settings.discoveryAdultLocked")
                : t("guilds:settings.discoveryAdultHint")}
            </p>
          </div>

          {error ? <p className="text-destructive text-sm">{error}</p> : null}
          {message ? <p className="text-primary text-sm">{message}</p> : null}
        </CardContent>
      </Card>

      <PublishGuildDialog
        open={publishing}
        saving={saving}
        initialCategories={activeGuild.categories}
        onCancel={() => setPublishing(false)}
        onConfirm={async (categories) => {
          const ok = await save({
            is_community: true,
            categories,
            // Ticking the certification in the dialog is what answers the 18+
            // question; there is no other path from unanswered to "no".
            has_adult_content: false,
          });
          if (ok) setPublishing(false);
        }}
      />
    </>
  );
};
