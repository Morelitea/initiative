import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { AnnouncementRead } from "@/api/generated/initiativeAPI.schemas";

import { AnnouncementsArchivePage } from "./AnnouncementsArchivePage";

const announcement = (overrides: Partial<AnnouncementRead> = {}): AnnouncementRead => ({
  key: "db:1",
  title: "Board view is new",
  category: "feature",
  sections: [{ heading: "Look", body: "At this" }],
  published_at: "2026-09-01T00:00:00Z",
  is_builtin: false,
  dismissals_required: 1,
  dismiss_count: 0,
  ...overrides,
});

const unread = announcement({ key: "db:1", title: "Not seen yet", dismiss_count: 0 });
const read = announcement({
  key: "db:2",
  title: "Dealt with",
  dismiss_count: 1,
  dismissed_at: "2026-09-02T00:00:00Z",
});

const listResponds = (items: AnnouncementRead[]) => {
  server.use(http.get("*/api/v1/announcements", () => HttpResponse.json({ items })));
};

describe("AnnouncementsArchivePage", () => {
  it("marks each notice read or unread", async () => {
    listResponds([unread, read]);

    renderWithProviders(<AnnouncementsArchivePage />);

    expect(await screen.findByText("Not seen yet")).toBeInTheDocument();
    expect(screen.getByText("Unread")).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
  });

  it("filters down to the unread ones", async () => {
    const user = userEvent.setup();
    listResponds([unread, read]);

    renderWithProviders(<AnnouncementsArchivePage />);

    await screen.findByText("Dealt with");
    expect(screen.getByRole("radio", { name: "All (2)" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Unread (1)" }));

    expect(screen.getByText("Not seen yet")).toBeInTheDocument();
    expect(screen.queryByText("Dealt with")).not.toBeInTheDocument();
  });

  it("says so when nothing is unread", async () => {
    const user = userEvent.setup();
    listResponds([read]);

    renderWithProviders(<AnnouncementsArchivePage />);

    await screen.findByText("Dealt with");
    await user.click(screen.getByRole("radio", { name: "Unread (0)" }));

    expect(screen.getByText(/all caught up/i)).toBeInTheDocument();
  });

  it("opens one to read it in full", async () => {
    const user = userEvent.setup();
    listResponds([unread]);

    renderWithProviders(<AnnouncementsArchivePage />);

    await user.click(await screen.findByRole("button", { name: /read it/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Not seen yet");
  });

  it("shows an empty state when nothing has been announced", async () => {
    listResponds([]);

    renderWithProviders(<AnnouncementsArchivePage />);

    await waitFor(() =>
      expect(screen.getByText(/nothing has been announced/i)).toBeInTheDocument()
    );
  });
});
