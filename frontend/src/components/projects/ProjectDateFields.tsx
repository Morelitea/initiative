import { useTranslation } from "react-i18next";

import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Label } from "@/components/ui/label";
import { parseDateValue } from "@/lib/formatDate";

type ProjectDateFieldsProps = {
  /** Namespaces the two field ids so several instances can share a page. */
  idPrefix: string;
  /** `YYYY-MM-DD`, or "" for unset — the shape `DateTimePicker` speaks. */
  startDate: string;
  endDate: string;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  disabled?: boolean;
};

/**
 * The optional start/end date pair for a project, shared by the create dialog
 * and project settings. Each date stands alone; whichever one is already set
 * bounds the other's calendar so a range can't be inverted.
 */
export const ProjectDateFields = ({
  idPrefix,
  startDate,
  endDate,
  onStartDateChange,
  onEndDateChange,
  disabled = false,
}: ProjectDateFieldsProps) => {
  const { t } = useTranslation(["projects", "common"]);
  const startBound = parseDateValue(startDate);
  const endBound = parseDateValue(endDate);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-start-date`}>{t("projects:schedule.startLabel")}</Label>
        <DateTimePicker
          id={`${idPrefix}-start-date`}
          value={startDate}
          onChange={onStartDateChange}
          includeTime={false}
          disabled={disabled}
          placeholder={t("common:optional")}
          calendarProps={endBound ? { hidden: { after: endBound } } : undefined}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-end-date`}>{t("projects:schedule.endLabel")}</Label>
        <DateTimePicker
          id={`${idPrefix}-end-date`}
          value={endDate}
          onChange={onEndDateChange}
          includeTime={false}
          disabled={disabled}
          placeholder={t("common:optional")}
          calendarProps={startBound ? { hidden: { before: startBound } } : undefined}
        />
      </div>
    </div>
  );
};
