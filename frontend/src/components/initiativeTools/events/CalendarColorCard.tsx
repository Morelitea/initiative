import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { useUpdateCalendar } from "@/hooks/useCalendars";
import { toast } from "@/lib/chesterToast";

type CalendarColorCardProps = {
  calendarId: number;
  initialColor: string | null;
  disabled?: boolean;
};

/**
 * Calendars' only tool-specific setting: the color their events render in.
 * Persists on pick, the way tags do, so it needs no Save button of its own.
 */
export const CalendarColorCard = ({
  calendarId,
  initialColor,
  disabled,
}: CalendarColorCardProps) => {
  const { t } = useTranslation(["calendars", "common"]);
  const [color, setColor] = useState(initialColor ?? "");

  const updateCalendar = useUpdateCalendar(calendarId, {
    onSuccess: () => toast.success(t("common:toolSettings.detailsUpdated")),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("calendarColor")}</CardTitle>
      </CardHeader>
      <CardContent>
        <ColorPickerPopover
          id="calendar-color"
          value={color}
          onChange={setColor}
          onChangeComplete={(next) => {
            const previous = color;
            setColor(next);
            updateCalendar.mutate({ color: next || null }, { onError: () => setColor(previous) });
          }}
          disabled={disabled}
        />
      </CardContent>
    </Card>
  );
};
