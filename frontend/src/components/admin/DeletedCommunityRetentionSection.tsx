/**
 * Platform → Communities: how long a deleted community is kept before it is
 * destroyed.
 *
 * The figure is the deployment's, one answer for everybody on the server. A
 * community cannot shorten or extend its own, which is what makes the window
 * mean something to the person deleting theirs.
 *
 * Blank means never. A deployment that has undertaken to keep what its members
 * put in it says so by clearing the box, and deleted communities then sit in
 * the operator's list until somebody restores or removes one deliberately.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCommunitySettings, useUpdateCommunitySettings } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

const MIN_DAYS = 1;
const MAX_DAYS = 3650;

export const DeletedCommunityRetentionSection = ({
  directoryEnabled,
}: {
  directoryEnabled: boolean;
}) => {
  const query = useCommunitySettings();
  if (!query.data) return null;

  // Mounted once the stored figure is known, so the box is not reset under
  // whoever is typing in it.
  return (
    <RetentionForm
      days={query.data.deleted_community_retention_days ?? null}
      directoryEnabled={directoryEnabled}
    />
  );
};

const RetentionForm = ({
  days,
  directoryEnabled,
}: {
  days: number | null;
  directoryEnabled: boolean;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const [value, setValue] = useState(days === null ? "" : String(days));
  const update = useUpdateCommunitySettings({
    onSuccess: (result) =>
      toast.success(
        result.deleted_community_retention_days === null
          ? t("community.retention.savedNever")
          : t("community.retention.saved", {
              count: result.deleted_community_retention_days,
            })
      ),
    onError: (err) => toast.error(getErrorMessage(err, "settings:community.saveError")),
  });

  const trimmed = value.trim();
  const parsed = trimmed === "" ? null : Number.parseInt(trimmed, 10);
  const valid =
    parsed === null || (Number.isInteger(parsed) && parsed >= MIN_DAYS && parsed <= MAX_DAYS);
  const changed = (days === null ? "" : String(days)) !== trimmed;

  return (
    <SettingsSection
      title={t("community.retention.title")}
      description={t("community.retention.description")}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="deleted-community-retention">{t("community.retention.label")}</Label>
          <Input
            id="deleted-community-retention"
            type="number"
            min={MIN_DAYS}
            max={MAX_DAYS}
            className="w-40"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={t("community.retention.placeholder")}
          />
        </div>
        <Button
          // Two of these sit on this page, so each says what it saves rather
          // than both being "Save" to anybody who cannot see which box it is by.
          aria-label={t("community.retention.save")}
          disabled={!valid || !changed || update.isPending}
          onClick={() =>
            update.mutate({
              // The endpoint writes the directory switch unconditionally, so
              // it is sent back as it stands rather than flipped by a save
              // about something else.
              community_directory_enabled: directoryEnabled,
              deleted_community_retention_days: parsed,
            })
          }
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        {parsed === null ? t("community.retention.neverHint") : t("community.retention.hint")}
      </p>
    </SettingsSection>
  );
};
