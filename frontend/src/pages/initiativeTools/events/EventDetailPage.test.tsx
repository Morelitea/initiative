/**
 * An event's page, as its readers and the people who change it use it: every
 * field saved on its own, and a repeating event asked which dates a change is
 * for.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildCalendarEvent } from "@/__tests__/factories";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { CalendarEventRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/mascotToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { EventDetailPage } from "./EventDetailPage";

const EVENT_ROUTE = "/c/$communityId/i/$initiativeId/calendars/$calendarId/events/$eventId";
const PARAMS = { communityId: "1", initiativeId: "1", calendarId: "1", eventId: "9" };

/** What each change sent, in order, without the zone every one carries. */
let sent: Record<string, unknown>[] = [];

/** Serves `event` as it stands, and each change as `answer` says. */
const serve = (
  event: CalendarEventRead,
  answer: (body: Record<string, unknown>) => Response | CalendarEventRead = (body) =>
    Object.assign(event, body)
) =>
  server.use(
    communityHttp.get("/calendar-events/:eventId", () => HttpResponse.json(event)),
    communityHttp.patch("/calendar-events/:eventId", async ({ request }) => {
      const { tz: _tz, ...body } = (await request.json()) as Record<string, unknown>;
      sent.push(body);
      const answered = answer(body);
      return answered instanceof Response ? answered : HttpResponse.json(answered);
    })
  );

const open = (search: Record<string, unknown> = {}) =>
  renderPage(EventDetailPage, {
    initialRoute: EVENT_ROUTE,
    routeParams: PARAMS,
    routerSearch: search,
  });

beforeEach(() => {
  sent = [];
});

describe("an event's page", () => {
  it("saves a field on its own, and only that field", async () => {
    serve(buildCalendarEvent({ id: 9, title: "Standup", location: "Room 2" }));
    open();
    const user = userEvent.setup();

    const title = await screen.findByDisplayValue("Standup");
    await user.clear(title);
    await user.type(title, "Retro{Enter}");

    await waitFor(() => expect(sent).toEqual([{ title: "Retro" }]));
    expect(screen.getByDisplayValue("Room 2")).toBeInTheDocument();
  });

  it("shows a reader who cannot change it what it is, and nothing to change", async () => {
    serve(
      buildCalendarEvent({
        id: 9,
        title: "Standup",
        description: "Bring the numbers",
        location: "Room 2",
        can: { edit: false },
      })
    );
    open();

    expect(await screen.findByText("Bring the numbers")).toBeInTheDocument();
    expect(screen.getByText("Room 2")).toBeInTheDocument();
    expect(screen.getByText("You can see this event, but not change it.")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Standup")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /more actions/i })).not.toBeInTheDocument();
  });

  it("asks which dates of a repeating event a change is for, and opens the date made its own", async () => {
    const series = buildCalendarEvent({
      id: 9,
      location: "Room 2",
      recurrence: "RRULE:FREQ=WEEKLY",
    });
    serve(series, (body) => ({ ...series, ...body, id: 42, series_id: 9, recurrence: null }));
    const { router } = open({ occurrence: "2026-10-27T15:00:00.000Z" });
    const user = userEvent.setup();

    const location = await screen.findByDisplayValue("Room 2");
    await user.clear(location);
    await user.type(location, "Room 3{Enter}");
    expect(await screen.findByText("Change a repeating event")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(sent).toEqual([
        { location: "Room 3", scope: "this", occurrence: "2026-10-27T15:00:00.000Z" },
      ])
    );
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/c/1/i/1/calendars/1/events/42")
    );
  });

  it("refuses a description written over one since changed, and can overwrite it", async () => {
    const event = buildCalendarEvent({ id: 9, description: "Old" });
    serve(event, (body) => {
      if (body.description_base === "Old") {
        // Someone else's change landed first.
        event.description = "Theirs";
        return HttpResponse.json({ detail: "CALENDAR_EVENT_DESCRIPTION_CHANGED" }, { status: 409 });
      }
      return Object.assign(event, { description: body.description });
    });
    open();
    const user = userEvent.setup();

    const description = await screen.findByDisplayValue("Old");
    await user.clear(description);
    await user.type(description, "Mine");
    await user.tab();
    await user.click(await screen.findByRole("button", { name: "Overwrite" }));

    await waitFor(() =>
      expect(sent).toEqual([
        { description: "Mine", description_base: "Old" },
        { description: "Mine", description_base: "Theirs" },
      ])
    );
  });
});
