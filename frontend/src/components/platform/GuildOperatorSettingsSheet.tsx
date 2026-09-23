/**
 * Everything an operator sets for one community, in one place.
 *
 * These are the settings a community's own admins cannot reach: the caps, what
 * it may do about its own sign-in, and which features it has. They used to be
 * a column each in the Guilds table, which stopped scaling — the banner
 * entitlement shipped with no control at all because there was nowhere to put
 * it. A table row is a poor form, and the set only grows.
 *
 * Each control saves on its own, the way the cells did: the operator endpoint
 * takes any subset, so there is no Save button to forget and no dirty state to
 * lose.
 *
 * Where the billing service sets each community's plan, the caps and
 * entitlements are the plan's: they are shown, not set, and a button opens the
 * community in billing to change them.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  GuildAuthOption,
  PlatformGuildStorageRead,
} from "@/api/generated/initiativeAPI.schemas";
import { GuildStatus } from "@/api/generated/initiativeAPI.schemas";
import { useReadIntakeSettingsApiV1SettingsIntakeGet } from "@/api/generated/intake/intake";
import { BillingConsoleButton } from "@/components/platform/BillingConsoleButton";
import { GuildRestoreWizard } from "@/components/platform/GuildRestoreWizard";
import { Section, SettingRow } from "@/components/platform/SettingRow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import {
  useAgreeGuildNarrowing,
  useGuildNarrowings,
  useUpdateGuildStorage,
} from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

const GIB = 1024 ** 3;

const parseGbInput = (raw: string): { bytes: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { bytes: null, invalid: false }; // blank = unlimited
  const gb = Number(trimmed);
  if (!Number.isFinite(gb) || gb < 0) return { bytes: null, invalid: true };
  return { bytes: Math.round(gb * GIB), invalid: false };
};

const bytesToGbInput = (bytes: number | null): string =>
  bytes == null ? "" : String(Number((bytes / GIB).toFixed(2)));

const parseUserLimitInput = (raw: string): { limit: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { limit: null, invalid: false }; // blank = unlimited
  const n = Number(trimmed);
  if (!Number.isInteger(n) || n < 1) return { limit: null, invalid: true };
  return { limit: n, invalid: false };
};

const userLimitToInput = (limit: number | null): string => (limit == null ? "" : String(limit));

export const GuildOperatorSettingsSheet = ({
  guild,
  open,
  onOpenChange,
}: {
  guild: PlatformGuildStorageRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t, i18n } = useTranslation("settings");
  const { billing } = useAppConfig();
  const planIsBillings = billing?.manages_plans ?? false;

  const [storageDraft, setStorageDraft] = useState("");
  const [usersDraft, setUsersDraft] = useState("");
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  const [restoring, setRestoring] = useState(false);

  /** Show what is stored, so a box never presents an unsaved value as saved. */
  const syncDrafts = (row: { max_storage_bytes: number | null; max_users: number | null }) => {
    setStorageDraft(bytesToGbInput(row.max_storage_bytes));
    setUsersDraft(userLimitToInput(row.max_users));
  };

  const update = useUpdateGuildStorage({
    // A save that normalised a value ("10.0" -> "10") answers with what it
    // stored, and that is what the boxes then show.
    onSuccess: (row) => {
      syncDrafts(row);
      toast.success(t("guilds.saved", { name: row.name }));
    },
    // A refused save leaves the old value in place, so the boxes go back to it
    // rather than keeping a number nothing accepted.
    onError: (err) => {
      if (guild) syncDrafts(guild);
      toast.error(getErrorMessage(err, "settings:guilds.saveError"));
    },
  });

  const intake = useReadIntakeSettingsApiV1SettingsIntakeGet({
    query: { enabled: open, staleTime: 60_000 },
  });

  // The drafts follow whichever community the sheet was opened for.
  if (guild && loadedFor !== guild.id) {
    setLoadedFor(guild.id);
    syncDrafts(guild);
  }

  if (!guild) return null;

  const patch = (data: Parameters<typeof update.mutate>[0]["data"]) =>
    update.mutate({ guildId: guild.id, data });

  const commitStorage = () => {
    const stored = guild.max_storage_bytes ?? null;
    const { bytes, invalid } = parseGbInput(storageDraft);
    // A malformed entry snaps back to the persisted value rather than saving.
    if (invalid || bytes === stored) {
      setStorageDraft(bytesToGbInput(stored));
      return;
    }
    patch({ max_storage_bytes: bytes });
  };

  const commitUsers = () => {
    const stored = guild.max_users ?? null;
    const { limit, invalid } = parseUserLimitInput(usersDraft);
    if (invalid || limit === stored) {
      setUsersDraft(userLimitToInput(stored));
      return;
    }
    patch({ max_users: limit });
  };

  // Help requests become cases in the deployment's support stream, so the
  // switch is only meaningful once something is bound to receive them. Read
  // here rather than inferred from the community: the binding is the
  // deployment's, one for all of them.
  const supportBound = (intake.data?.bindings ?? []).some(
    (binding) => binding.stream === "support" && binding.enabled && binding.project_id !== null
  );

  const options = guild.auth_options ?? [];
  const toggleOption = (option: GuildAuthOption, checked: boolean) =>
    patch({
      auth_options: checked ? [...options, option] : options.filter((held) => held !== option),
    });

  // A deleted community is on its way out. Its caps and entitlements are
  // settings for a community nobody can reach, so they are shown and frozen
  // rather than hidden — what it was configured as is worth seeing when you
  // are deciding whether to bring it back.
  const deleted = guild.status === GuildStatus.deleted;
  // What locks the plan's own controls: a community on its way out, or a plan
  // that billing sets.
  const planLocked = deleted || planIsBillings;
  const purgeDate = guild.purge_at
    ? new Date(guild.purge_at).toLocaleDateString(i18n.resolvedLanguage ?? i18n.language, {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {guild.name}
            {guild.tier_name ? <Badge variant="secondary">{guild.tier_name}</Badge> : null}
          </SheetTitle>
          <SheetDescription>{t("guilds.sheet.description")}</SheetDescription>
        </SheetHeader>

        <div className="space-y-6 py-6">
          {deleted ? (
            <Section title={t("guilds.sheet.deleted")}>
              <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-4">
                <p className="text-sm">
                  {purgeDate
                    ? t("guilds.restore.purgesOn", { date: purgeDate })
                    : t("guilds.restore.purgesSoon")}
                </p>
                <p className="text-muted-foreground text-xs">{t("guilds.restore.retained")}</p>
                <Button size="sm" onClick={() => setRestoring(true)}>
                  {t("guilds.restore.open")}
                </Button>
              </div>
            </Section>
          ) : null}

          {planIsBillings && !deleted ? (
            <div className="space-y-3 rounded-md border bg-muted/40 p-4">
              <p className="text-sm">{t("guilds.sheet.setInBilling")}</p>
              {billing?.operator_handoff ? (
                <BillingConsoleButton guild={guild} console="operator" size="sm">
                  {t("guilds.sheet.changeInBilling")}
                </BillingConsoleButton>
              ) : null}
            </div>
          ) : null}

          <Section title={t("guilds.sheet.limits")}>
            <SettingRow
              label={t("guilds.sheet.usersLabel")}
              help={t("guilds.sheet.usersHelp")}
              htmlFor="guild-max-users"
              control={
                <Input
                  id="guild-max-users"
                  type="number"
                  min={1}
                  step={1}
                  inputMode="numeric"
                  className="w-32"
                  value={usersDraft}
                  onChange={(event) => setUsersDraft(event.target.value)}
                  onBlur={commitUsers}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") event.currentTarget.blur();
                  }}
                  placeholder={t("guilds.unlimitedPlaceholder")}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("guilds.sheet.storageLabel")}
              help={t("guilds.sheet.storageHelp")}
              htmlFor="guild-max-storage"
              control={
                <div className="relative w-32">
                  <Input
                    id="guild-max-storage"
                    type="number"
                    min={0}
                    step="any"
                    inputMode="decimal"
                    className="pr-9"
                    value={storageDraft}
                    onChange={(event) => setStorageDraft(event.target.value)}
                    onBlur={commitStorage}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") event.currentTarget.blur();
                    }}
                    placeholder={t("guilds.unlimitedPlaceholder")}
                    disabled={update.isPending || planLocked}
                  />
                  <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground text-xs">
                    GB
                  </span>
                </div>
              }
            />
          </Section>

          {/* Two separate grants. Either one can be given on its own. */}
          <Section title={t("guilds.sheet.decidesForItself")}>
            <SettingRow
              label={t("guilds.sheet.authOption.providers.label")}
              help={t("guilds.sheet.authOption.providers.help")}
              htmlFor="guild-auth-providers"
              control={
                <Switch
                  id="guild-auth-providers"
                  checked={options.includes("providers")}
                  onCheckedChange={(checked) => toggleOption("providers", Boolean(checked))}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("guilds.sheet.authOption.restrictions.label")}
              help={t("guilds.sheet.authOption.restrictions.help")}
              htmlFor="guild-auth-restrictions"
              control={
                <Switch
                  id="guild-auth-restrictions"
                  checked={options.includes("restrictions")}
                  onCheckedChange={(checked) => toggleOption("restrictions", Boolean(checked))}
                  disabled={update.isPending || planLocked}
                />
              }
            />
          </Section>

          <NarrowingsSection guildId={guild.id} disabled={deleted} />

          <Section title={t("guilds.sheet.features")}>
            <SettingRow
              label={t("guilds.sheet.bannerLabel")}
              help={t("guilds.sheet.bannerHelp")}
              htmlFor="guild-banner-image"
              control={
                <Switch
                  id="guild-banner-image"
                  checked={guild.banner_image_enabled}
                  onCheckedChange={(checked) => patch({ banner_image_enabled: Boolean(checked) })}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("guilds.sheet.supportLabel")}
              help={
                supportBound || guild.support_enabled
                  ? t("guilds.sheet.supportHelp")
                  : t("guilds.sheet.supportNeedsIntake")
              }
              htmlFor="guild-support"
              control={
                <Switch
                  id="guild-support"
                  checked={guild.support_enabled}
                  onCheckedChange={(checked) => patch({ support_enabled: Boolean(checked) })}
                  // Switching it off stays available wherever it is on: a
                  // deployment that has stopped staffing help stops offering
                  // it, binding or no binding.
                  disabled={
                    update.isPending || planLocked || (!supportBound && !guild.support_enabled)
                  }
                />
              }
            />
          </Section>
        </div>
      </SheetContent>
      {restoring ? (
        <GuildRestoreWizard guild={guild} open={restoring} onOpenChange={setRestoring} />
      ) : null}
    </Sheet>
  );
};

/**
 * What a community says its own arrivals look like, and whether anybody has
 * agreed.
 *
 * A community writes its own claim values and nothing in the app can tell
 * whether it holds the domain or tenant they name, so the answer is the
 * deployment's. Support answers through the case raised when they are
 * written; this is the same question where a deployment runs no intake, and
 * where an answer is withdrawn either way.
 */
const NarrowingsSection = ({ guildId, disabled }: { guildId: number; disabled: boolean }) => {
  const { t } = useTranslation("settings");
  const narrowings = useGuildNarrowings(guildId);
  const agree = useAgreeGuildNarrowing(guildId, {
    onError: (err: unknown) =>
      toast.error(getErrorMessage(err, "settings:guilds.sheet.narrowings.error")),
  });

  const rows = narrowings.data ?? [];
  if (narrowings.isLoading || rows.length === 0) return null;

  return (
    <Section title={t("guilds.sheet.narrowings.title")}>
      <p className="text-muted-foreground text-sm">{t("guilds.sheet.narrowings.help")}</p>
      <ul className="space-y-3">
        {rows.map((row) => (
          <li
            key={row.connection_id}
            className="flex items-start justify-between gap-3 rounded-md border px-3 py-3"
          >
            <div className="min-w-0 space-y-1">
              <p className="font-medium text-sm">
                {t("guilds.sheet.narrowings.claims", {
                  provider: row.provider_display_name,
                  claim: row.claim,
                  values: row.claim_values.join(", "),
                })}
              </p>
              <p className="text-muted-foreground text-xs">
                {row.auto_join
                  ? t("guilds.sheet.narrowings.joinsOnArrival")
                  : t("guilds.sheet.narrowings.admitsOnly")}
              </p>
            </div>
            <Button
              size="sm"
              variant={row.agreed ? "outline" : "default"}
              disabled={disabled || agree.isPending}
              onClick={() =>
                agree.mutate({
                  connectionId: row.connection_id,
                  agreed: !row.agreed,
                })
              }
            >
              {row.agreed
                ? t("guilds.sheet.narrowings.withdraw")
                : t("guilds.sheet.narrowings.agree")}
            </Button>
          </li>
        ))}
      </ul>
    </Section>
  );
};
