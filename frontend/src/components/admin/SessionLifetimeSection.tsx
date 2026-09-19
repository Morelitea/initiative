/**
 * Platform → Security: how long somebody may stay signed in before signing in
 * again.
 *
 * A different question from how long a session may be left alone, which the
 * deployment's configuration holds: this one nothing pushes forward. Blank
 * asks for no limit, which is where a self-hosted deployment starts.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SettingsSection } from "@/components/settings/SettingsSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { usePlatformAuthSettings, useUpdateSessionLifetime } from "@/hooks/useSettings";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export const SessionLifetimeSection = () => {
  const query = usePlatformAuthSettings();
  if (query.isLoading || !query.data) return null;

  // The field starts from the stored figure, so the form is mounted once that
  // figure is known rather than reset underneath whoever is typing.
  return <SessionLifetimeForm hours={query.data.session_max_hours ?? null} />;
};

const SessionLifetimeForm = ({ hours }: { hours: number | null }) => {
  const { t } = useTranslation(["settings", "common"]);
  const [value, setValue] = useState(hours === null ? "" : String(hours));
  const update = useUpdateSessionLifetime({
    onSuccess: () => toast.success(t("auth.sessionLifetime.saved")),
    onError: (err) => toast.error(getErrorMessage(err, "settings:auth.sessionLifetime.error")),
  });

  const trimmed = value.trim();
  const parsed = trimmed === "" ? null : Number.parseInt(trimmed, 10);
  const valid = parsed === null || (Number.isFinite(parsed) && parsed >= 1);
  const changed = (hours === null ? "" : String(hours)) !== trimmed;

  return (
    <SettingsSection
      title={t("auth.sessionLifetime.title")}
      description={t("auth.sessionLifetime.description")}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="session-max-hours">{t("auth.sessionLifetime.label")}</Label>
          <Input
            id="session-max-hours"
            type="number"
            min={1}
            className="w-40"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={t("auth.sessionLifetime.placeholder")}
          />
        </div>
        <Button
          disabled={!valid || !changed || update.isPending}
          onClick={() => update.mutate({ session_max_hours: parsed })}
        >
          {update.isPending ? t("common:submitting") : t("common:save")}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">{t("auth.sessionLifetime.hint")}</p>
    </SettingsSection>
  );
};
