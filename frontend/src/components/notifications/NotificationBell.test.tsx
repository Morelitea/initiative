import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories/notification.factory";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { NotificationRead, NotificationType } from "@/api/generated/initiativeAPI.schemas";

import { NotificationBell } from "./NotificationBell";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
// The bell reads the push channel's state to decide whether it still needs a
// timer; the socket itself is exercised in useNotificationStream.test.tsx.
let streamConnected = false;
vi.mock("@/hooks/useNotificationStream", () => ({
  useNotificationStreamConnected: () => streamConnected,
}));
vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { downloadBlob } from "@/lib/csv";

const PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"

const mockInbox = (notifications: NotificationRead[]) => {
  server.use(
    http.get("/api/v1/notifications/", () =>
      HttpResponse.json({
        notifications,
        unread_count: notifications.filter((n) => !n.read_at).length,
      })
    ),
    http.post("/api/v1/notifications/:id/read", () => HttpResponse.json({}))
  );
};

describe("NotificationBell export notifications", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("downloads the artifact when an export_ready notification is clicked", async () => {
    mockInbox([
      buildNotification({
        type: "export_ready" as NotificationType,
        data: { guild_id: 1, export_job_id: 42, source: "tasks", format: "pdf" },
      }),
    ]);
    server.use(
      http.get(
        "/api/v1/g/1/exports/42/download",
        () =>
          new HttpResponse(PDF, {
            status: 200,
            headers: { "Content-Type": "application/pdf" },
          })
      )
    );
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    const item = await screen.findByText(/export is ready/i);
    await userEvent.click(item);

    await waitFor(() => expect(downloadBlob).toHaveBeenCalledTimes(1));
    expect(vi.mocked(downloadBlob).mock.calls[0][1]).toBe("tasks-42.pdf");
  });

  it("renders a failed export notification without a download", async () => {
    mockInbox([
      buildNotification({
        type: "export_failed" as NotificationType,
        data: { guild_id: 1, export_job_id: 43, source: "tasks", format: "pdf" },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    const item = await screen.findByText(/export failed/i);
    await userEvent.click(item);

    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("renders import notifications with their own text, not the generic fallback", async () => {
    mockInbox([
      buildNotification({
        type: "import_ready" as NotificationType,
        data: { guild_id: 1, import_job_id: 7, source: "backup" },
      }),
      buildNotification({
        id: 2,
        type: "import_failed" as NotificationType,
        data: { guild_id: 1, import_job_id: 8, source: "initiative-queue" },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));
    // Each import type renders its own text, not the generic fallback — the
    // bug was both showing "You have a new notification".
    expect(await screen.findByText(/import finished/i)).toBeInTheDocument();
    expect(screen.getByText(/import failed/i)).toBeInTheDocument();
    expect(screen.queryByText(/new notification/i)).not.toBeInTheDocument();
    // Imports navigate to the Data-tab report rather than downloading.
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it("says who knocked and how it was answered, not the generic fallback", async () => {
    mockInbox([
      buildNotification({
        type: "initiative_join_requested" as NotificationType,
        data: {
          guild_id: 1,
          initiative_id: 5,
          initiative_name: "Apollo",
          requester_name: "Ada Lovelace",
          target_path: "/i/5/settings/members",
        },
      }),
      buildNotification({
        id: 2,
        type: "initiative_join_approved" as NotificationType,
        data: { guild_id: 1, initiative_id: 5, initiative_name: "Apollo" },
      }),
      buildNotification({
        id: 3,
        type: "initiative_join_denied" as NotificationType,
        data: { guild_id: 1, initiative_id: 6, initiative_name: "Vanguard" },
      }),
    ]);
    renderWithProviders(<NotificationBell />);

    await userEvent.click(screen.getByRole("button", { name: /notifications/i }));

    expect(await screen.findByText(/Ada Lovelace asked to join Apollo/i)).toBeInTheDocument();
    expect(screen.getByText(/request to join Apollo was approved/i)).toBeInTheDocument();
    expect(screen.getByText(/request to join Vanguard was declined/i)).toBeInTheDocument();
    expect(screen.queryByText(/new notification/i)).not.toBeInTheDocument();
  });
});

describe("NotificationBell polling fallback", () => {
  const countInboxRequests = () => {
    let requests = 0;
    server.use(
      http.get("/api/v1/notifications/", () => {
        requests += 1;
        return HttpResponse.json({ notifications: [], unread_count: 0 });
      })
    );
    return () => requests;
  };

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
    streamConnected = false;
  });

  it("does not poll while the push channel is open", async () => {
    streamConnected = true;
    const requests = countInboxRequests();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(requests()).toBe(1));

    await vi.advanceTimersByTimeAsync(120_000);

    // The socket refetches this query itself; a timer would only duplicate it.
    expect(requests()).toBe(1);
  });

  it("keeps polling when the push channel cannot connect", async () => {
    streamConnected = false;
    const requests = countInboxRequests();
    renderWithProviders(<NotificationBell />);
    await waitFor(() => expect(requests()).toBe(1));

    await vi.advanceTimersByTimeAsync(31_000);

    // Losing the socket must not mean losing notifications.
    await waitFor(() => expect(requests()).toBeGreaterThan(1));
  });
});
