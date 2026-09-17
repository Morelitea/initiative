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
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  GuildAuthOption,
  PlatformGuildStorageRead,
} from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { useUpdateGuildStorage } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";
import { cn } from "@/lib/utils";

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

/** One labelled control with its explanation, so every row reads the same. */
const SettingRow = ({
  label,
  help,
  htmlFor,
  control,
  nested = false,
}: {
  label: string;
  help: string;
  htmlFor?: string;
  control: React.ReactNode;
  /** Renders indented under the row above, for a setting that reads as part of it. */
  nested?: boolean;
}) => (
  <div
    className={cn(
      "flex items-start justify-between gap-6 py-3",
      nested && "ml-3 border-border border-l pl-4"
    )}
  >
    <div className="space-y-1">
      <Label htmlFor={htmlFor} className="font-medium">
        {label}
      </Label>
      <p className="text-muted-foreground text-sm">{help}</p>
    </div>
    <div className="shrink-0 pt-0.5">{control}</div>
  </div>
);

const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="space-y-1">
    <h3 className="font-semibold text-sm">{title}</h3>
    <Separator />
    <div className="divide-y">{children}</div>
  </section>
);

export const GuildOperatorSettingsSheet = ({
  guild,
  open,
  onOpenChange,
}: {
  guild: PlatformGuildStorageRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation("settings");

  const [storageDraft, setStorageDraft] = useState("");
  const [usersDraft, setUsersDraft] = useState("");
  const [loadedFor, setLoadedFor] = useState<number | null>(null);

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

  const options = guild.auth_options ?? [];
  const toggleOption = (option: GuildAuthOption, checked: boolean) =>
    patch({
      auth_options: checked ? [...options, option] : options.filter((held) => held !== option),
    });

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
                  disabled={update.isPending}
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
                    disabled={update.isPending}
                  />
                  <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground text-xs">
                    GB
                  </span>
                </div>
              }
            />
          </Section>

          <Section title={t("guilds.sheet.signIn")}>
            {(["providers", "require_sign_in"] as const).map((option) => (
              <SettingRow
                key={option}
                nested={option === "require_sign_in"}
                label={t(`guilds.sheet.authOption.${option}.label`)}
                help={t(`guilds.sheet.authOption.${option}.help`)}
                htmlFor={`guild-auth-${option}`}
                control={
                  <Checkbox
                    id={`guild-auth-${option}`}
                    checked={options.includes(option)}
                    onCheckedChange={(checked) => toggleOption(option, Boolean(checked))}
                    disabled={update.isPending}
                  />
                }
              />
            ))}
            <SettingRow
              label={t("guilds.sheet.complianceSessionLabel")}
              help={t("guilds.sheet.complianceSessionHelp")}
              htmlFor="guild-compliance-session"
              control={
                <Switch
                  id="guild-compliance-session"
                  checked={guild.enforce_compliance_session}
                  onCheckedChange={(checked) =>
                    patch({ enforce_compliance_session: Boolean(checked) })
                  }
                  disabled={update.isPending}
                />
              }
            />
          </Section>

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
                  disabled={update.isPending}
                />
              }
            />
            <SettingRow
              label={t("guilds.sheet.supportLabel")}
              help={t("guilds.sheet.supportHelp")}
              htmlFor="guild-support"
              control={
                <Switch
                  id="guild-support"
                  checked={guild.support_enabled}
                  onCheckedChange={(checked) => patch({ support_enabled: Boolean(checked) })}
                  disabled={update.isPending}
                />
              }
            />
          </Section>
        </div>
      </SheetContent>
    </Sheet>
  );
};
