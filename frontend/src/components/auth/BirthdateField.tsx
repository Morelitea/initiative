import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * The question, and what happens to the answer.
 *
 * The note under the field is not decoration: somebody being asked their
 * birthday deserves to be told, in the same breath, that it is being used to
 * work out one thing and then dropped. It sits with the field rather than in
 * each caller so no surface can ask without saying so.
 */
export const BirthdateField = ({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation(["auth"]);
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("auth:confirmAge.birthdateLabel")}</Label>
      <Input
        id={id}
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        required
        // A birthday is nobody's business to complete for them, and the field
        // is asked once.
        autoComplete="off"
        max={new Date().toISOString().slice(0, 10)}
      />
      <p className="text-muted-foreground text-xs">{t("auth:confirmAge.privacyNote")}</p>
    </div>
  );
};
