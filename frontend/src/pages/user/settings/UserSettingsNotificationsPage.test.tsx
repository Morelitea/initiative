import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

// usePushNotifications pulls in a Capacitor plugin that can't load in jsdom.
vi.mock("@/hooks/usePushNotifications", () => ({
  usePushNotifications: () => ({
    permissionStatus: "prompt",
    requestPermission: vi.fn(),
    isSupported: false,
  }),
}));
vi.mock("@/hooks/useSettings", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/useSettings")>("@/hooks/useSettings");
  return { ...actual, useFcmConfig: () => ({ data: { enabled: false } }) };
});

import { UserSettingsNotificationsPage } from "./UserSettingsNotificationsPage";

describe("UserSettingsNotificationsPage", () => {
  const renderPage = (overrides = {}) =>
    renderWithProviders(
      <UserSettingsNotificationsPage
        user={buildUser({
          email_events: true,
          push_events: true,
          email_event_reminders: true,
          push_event_reminders: true,
          event_reminder_minutes_before: 15,
          ...overrides,
        })}
        refreshUser={vi.fn().mockResolvedValue(undefined)}
      />
    );

  it("renders the Events and Event reminders categories", async () => {
    renderPage();
    expect(await screen.findByText("Events")).toBeInTheDocument();
    expect(screen.getByText("Event reminders")).toBeInTheDocument();
  });

  it("shows the configured reminder lead time", async () => {
    renderPage({ event_reminder_minutes_before: 30 });
    // The Radix Select trigger renders the selected option's label.
    expect(await screen.findByText("30 minutes before")).toBeInTheDocument();
  });

  it("renders 'at the time of the event' when lead time is zero", async () => {
    renderPage({ event_reminder_minutes_before: 0 });
    expect(await screen.findByText("At the time of the event")).toBeInTheDocument();
  });
});
