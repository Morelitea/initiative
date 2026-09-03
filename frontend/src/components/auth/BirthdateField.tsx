import { useTranslation } from "react-i18next";

import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";

/**
 * The question, and what happens to the answer.
 *
 * The note under the field is not decoration: somebody being asked their
 * birthday deserves to be told, in the same breath, that it is being used to
 * work out one thing and then dropped. It sits with the field rather than in
 * each caller so no surface can ask without saying so.
 *
 * The date is picked with the same control as every other date in the app —
 * type it or reach it through the year dropdown — rather than the browser's
 * own, which differs on every platform and, on a birthday, means paging back
 * decades a month at a time.
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
  const today = new Date();
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("auth:confirmAge.birthdateLabel")}</Label>
      <DateTimePicker
        id={id}
        value={value}
        onChange={onChange}
        disabled={disabled}
        includeTime={false}
        placeholder={t("auth:confirmAge.birthdatePlaceholder")}
        calendarProps={{
          // A lifetime of years to choose from, and nothing ahead of today:
          // nobody was born tomorrow.
          startMonth: new Date(today.getFullYear() - 120, 0),
          endMonth: new Date(today.getFullYear(), today.getMonth()),
          hidden: { after: today },
        }}
      />
      <p className="text-muted-foreground text-xs">{t("auth:confirmAge.privacyNote")}</p>
    </div>
  );
};
