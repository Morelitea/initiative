import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories/notification.factory";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { NotificationRead, NotificationType } from "@/api/generated/initiativeAPI.schemas";

import { NotificationBell } from "./NotificationBell";

vi.mock("@/lib/csv", () => ({ downloadBlob: vi.fn() }));
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
});
