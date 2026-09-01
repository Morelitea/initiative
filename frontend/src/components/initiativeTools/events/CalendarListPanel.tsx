import { Link } from "@tanstack/react-router";
import { CalendarDays, ChevronDown, Plus, Settings2 } from "lucide-react";
import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import type { CalendarSummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

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

/** The calendar list panel behind a toolbar dropdown: a "Calendars" trigger
 * opening the visibility panel, so the calendar grid keeps the full page
 * width. The trigger carries how many calendars are switched off, so a
 * narrowed grid still says so with the panel shut. */
export const CalendarPanelDropdown = (props: ComponentProps<typeof CalendarListPanel>) => {
  const { t } = useTranslation("calendars");
  // Counted from the same predicates the rows render from, so the badge and
  // the checkboxes can never disagree.
  const hiddenCount =
    props.calendars.filter(props.isCalendarHidden).length +
    props.projectCalendars.filter(props.isProjectHidden).length;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant={hiddenCount > 0 ? "secondary" : "outline"} size="sm" className="h-9">
          <CalendarDays className="h-4 w-4" />
          {t("panel.calendars")}
          {hiddenCount > 0 ? (
            <>
              <span
                aria-hidden="true"
                className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 font-medium text-[11px] text-primary-foreground tabular-nums"
              >
                {hiddenCount}
              </span>
              <span className="sr-only">{t("panel.hiddenCount", { count: hiddenCount })}</span>
            </>
          ) : null}
          <ChevronDown className="h-4 w-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="max-h-96 w-80 overflow-y-auto">
        <CalendarListPanel {...props} />
      </PopoverContent>
    </Popover>
  );
};

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
        <h2 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
          {t("panel.calendars")}
        </h2>
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
        {/* Named rather than a bare "+" in the heading: adding a calendar is
            what this panel is for on the app's own surface, and an icon in a
            corner read as decoration. */}
        {canCreate && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-full justify-start gap-2 px-1 font-normal text-muted-foreground hover:text-foreground"
            onClick={onCreate}
          >
            <Plus className="h-4 w-4" />
            {t("createCalendar")}
          </Button>
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
