import { keepPreviousData } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { useSuggestUsernamesApiV1AuthUsernameSuggestionsGet } from "@/api/generated/auth/auth";
import { BirthdateField } from "@/components/auth/BirthdateField";
import type { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { ContinueButton, StepField } from "@/components/start/stepParts";
import { UsernameField } from "@/components/UsernameField";
import { Button } from "@/components/ui/button";
import { SearchableCombobox } from "@/components/ui/searchable-combobox";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { TIMEZONE_OPTIONS } from "@/lib/timezones";

/** How long typing settles before the suggestions start from it. */
const SEED_SETTLES_MS = 400;

/** Names nobody holds yet, starting from what is typed, to tap into the field. */
const HandleSuggestions = ({
  value,
  onPick,
  disabled,
}: {
  value: string;
  onPick: (name: string) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  const seed = useDebouncedValue(value.trim(), SEED_SETTLES_MS);
  const { data } = useSuggestUsernamesApiV1AuthUsernameSuggestionsGet(seed ? { seed } : undefined, {
    query: { placeholderData: keepPreviousData, retry: false },
  });
  const names = (data?.suggestions ?? []).filter((name) => name !== value.trim());
  if (!names.length) return null;
  return (
    <fieldset>
      <legend className="mb-1.5 text-muted-foreground text-xs">{t("start.you.suggestions")}</legend>
      <div className="flex flex-wrap gap-2">
        {names.map((name) => (
          <Button
            key={name}
            type="button"
            size="sm"
            variant="secondary"
            className="rounded-full"
            onClick={() => onPick(name)}
            disabled={disabled}
          >
            {name}
          </Button>
        ))}
      </div>
    </fieldset>
  );
};

/**
 * Who they are. Signed out that is the handle (required), the timezone, and
 * the birthdate where the deployment asks; signed in it is only ever the
 * birthdate, for joining.
 */
export const YouStep = ({
  signedIn,
  username,
  onUsernameChange,
  timezone,
  onTimezoneChange,
  age,
  asksAge,
  ageRequired,
  busy,
  onContinue,
}: {
  signedIn: boolean;
  username: string;
  onUsernameChange: (username: string) => void;
  timezone: string;
  onTimezoneChange: (timezone: string) => void;
  age: ReturnType<typeof useAgeConfirmation>;
  asksAge: boolean;
  ageRequired: boolean;
  busy: boolean;
  onContinue: () => void;
}) => {
  const { t } = useTranslation(["auth", "settings"]);
  const handleMissing = !signedIn && !username.trim();
  return (
    <>
      {signedIn ? null : (
        <>
          <div className="space-y-2">
            <UsernameField
              id="start-username"
              value={username}
              onChange={onUsernameChange}
              disabled={busy}
            />
            <HandleSuggestions value={username} onPick={onUsernameChange} disabled={busy} />
          </div>
          <StepField id="start-timezone" label={t("settings:profile.timezoneLabel")}>
            <SearchableCombobox
              items={TIMEZONE_OPTIONS.map((tz) => ({ value: tz, label: tz }))}
              value={timezone}
              onValueChange={onTimezoneChange}
              placeholder={t("settings:profile.timezonePlaceholder")}
              emptyMessage={t("settings:profile.timezoneEmpty")}
            />
          </StepField>
        </>
      )}
      {asksAge ? (
        <BirthdateField
          id="start-birthdate"
          value={age.birthdate}
          onChange={age.setBirthdate}
          disabled={busy || age.submitting}
        />
      ) : null}
      {age.error ? <p className="text-destructive text-sm">{age.error}</p> : null}
      <ContinueButton
        onClick={onContinue}
        disabled={busy || age.submitting || handleMissing || (ageRequired && !age.birthdate)}
      />
    </>
  );
};
