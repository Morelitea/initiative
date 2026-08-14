import { useParams } from "@tanstack/react-router";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CalendarColorCard } from "@/components/initiativeTools/events/CalendarColorCard";
import { ToolSettingsPage } from "@/components/tools/settings/ToolSettingsPage";
import {
  useCalendar,
  useDeleteCalendar,
  useSetCalendarGrants,
  useUpdateCalendar,
} from "@/hooks/useCalendars";
import { hasWriteAccess } from "@/lib/permissions";

/** The calendar's single sharing surface — its events inherit all of it. */
export function CalendarSettingsPage() {
  const { calendarId } = useParams({ strict: false }) as { calendarId?: string };
  const parsedId = calendarId ? Number(calendarId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const calendarQuery = useCalendar(isValidId ? parsedId : null);
  const update = useUpdateCalendar(parsedId);
  const setGrants = useSetCalendarGrants(parsedId);
  const remove = useDeleteCalendar();

  const calendar = calendarQuery.data;

  return (
    <ToolSettingsPage
      tool={Tool.calendar}
      entity={calendar}
      isLoading={isValidId && calendarQuery.isLoading}
      isError={!isValidId || calendarQuery.isError}
      update={update}
      setGrants={setGrants}
      remove={remove}
      detailsExtra={
        calendar ? (
          <CalendarColorCard
            calendarId={calendar.id}
            initialColor={calendar.color}
            disabled={!hasWriteAccess(calendar.my_permission_level)}
          />
        ) : null
      }
    />
  );
}
