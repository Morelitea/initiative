import { Link } from "@tanstack/react-router";
import { Plus, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CalendarSummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

/** A derived, read-only "calendar" for one project's tasks — rendered from the
 * calendar-entries tasks payload, never stored server-side. */
export interface ProjectTaskCalendar {
  projectId: number;
  guildId: number;
  name: string;
  color: string;
}

interface CalendarListPanelProps {
  calendars: CalendarSummary[];
  projectCalendars: ProjectTaskCalendar[];
  /** Callback predicates instead of id sets: callers own the keying (the My
   * Calendar page is cross-guild, where per-guild ids collide). Visibility
   * defaults ON so new calendars appear checked. */
  isCalendarHidden: (calendar: CalendarSummary) => boolean;
  isProjectHidden: (project: ProjectTaskCalendar) => boolean;
  onToggleCalendar: (calendar: CalendarSummary) => void;
  onToggleProject: (project: ProjectTaskCalendar) => void;
  /** Optional display label override (e.g. guild-suffixed cross-guild names). */
  calendarLabel?: (calendar: CalendarSummary) => string;
  /** Settings link target for a manageable calendar; null hides the link. */
  settingsPathFor?: (calendar: CalendarSummary) => string | null;
  canCreate: boolean;
  onCreate: () => void;
}

/** The calendar page's list panel — real calendars (color, visibility,
 * settings link) and one read-only task calendar per project, Google-Calendar
 * style. Sharing/rename/delete live on each calendar's settings page. */
export const CalendarListPanel = ({
  calendars,
  projectCalendars,
  isCalendarHidden,
  isProjectHidden,
  onToggleCalendar,
  onToggleProject,
  calendarLabel,
  settingsPathFor,
  canCreate,
  onCreate,
}: CalendarListPanelProps) => {
  const { t } = useTranslation("calendars");

  const canManage = (calendar: CalendarSummary) =>
    calendar.my_permission_level === "write" || calendar.my_permission_level === "owner";

  return (
    <div className="space-y-4">
      <section className="space-y-1">
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
            {t("panel.myCalendars")}
          </h2>
          {canCreate && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={onCreate}
              aria-label={t("createCalendar")}
            >
              <Plus className="h-4 w-4" />
            </Button>
          )}
        </div>
        {calendars.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("panel.noCalendars")}</p>
        ) : (
          <ul className="space-y-0.5">
            {calendars.map((calendar) => {
              const settingsPath = canManage(calendar)
                ? (settingsPathFor?.(calendar) ?? null)
                : null;
              return (
                <li
                  key={`${calendar.guild_id}-${calendar.id}`}
                  className="group flex items-center gap-2 rounded px-1 py-0.5"
                >
                  <Checkbox
                    id={`calendar-toggle-${calendar.guild_id}-${calendar.id}`}
                    checked={!isCalendarHidden(calendar)}
                    onCheckedChange={() => onToggleCalendar(calendar)}
                  />
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: calendar.color ?? "#6366f1" }}
                  />
                  <Label
                    htmlFor={`calendar-toggle-${calendar.guild_id}-${calendar.id}`}
                    className="min-w-0 flex-1 cursor-pointer truncate font-normal text-sm"
                  >
                    {calendarLabel?.(calendar) ?? calendar.name}
                  </Label>
                  {settingsPath && (
                    <Link
                      to={settingsPath}
                      className="invisible text-muted-foreground hover:text-foreground group-hover:visible"
                      aria-label={t("panel.calendarSettings", { name: calendar.name })}
                    >
                      <Settings2 className="h-4 w-4" />
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {projectCalendars.length > 0 && (
        <section className="space-y-1">
          <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
            {t("panel.projectTasks")}
          </h2>
          <ul className="space-y-0.5">
            {projectCalendars.map((project) => (
              <li
                key={`${project.guildId}-${project.projectId}`}
                className="flex items-center gap-2 rounded px-1 py-0.5"
              >
                <Checkbox
                  id={`project-calendar-toggle-${project.guildId}-${project.projectId}`}
                  checked={!isProjectHidden(project)}
                  onCheckedChange={() => onToggleProject(project)}
                />
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: project.color }}
                />
                <Label
                  htmlFor={`project-calendar-toggle-${project.guildId}-${project.projectId}`}
                  className="min-w-0 flex-1 cursor-pointer truncate font-normal text-sm"
                >
                  {project.name}
                </Label>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};
