import { waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildNotification } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { receiveAlert } from "@/lib/desktopAlerts";

import { useDesktopApp } from "./useDesktopApp";

const desktop = vi.hoisted(() => ({
  notify: vi.fn(async () => {}),
  setBadge: vi.fn(async () => {}),
  clicked: null as ((event: { tag: string }) => void) | null,
  navigate: vi.fn(),
}));

vi.mock("@capacitor/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@capacitor/core")>();
  return { ...actual, Capacitor: { ...actual.Capacitor, getPlatform: () => "electron" } };
});
vi.mock("@/plugins/desktop", () => ({
  default: {
    notify: desktop.notify,
    setBadge: desktop.setBadge,
    addListener: async (_event: string, listener: (event: { tag: string }) => void) => {
      desktop.clicked = listener;
      return { remove: async () => {} };
    },
  },
}));
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useRouter: () => ({ navigate: desktop.navigate }),
}));

const Probe = () => {
  useDesktopApp();
  return null;
};

const line = buildNotification({
  id: 7,
  type: "task_assignment",
  data: { task_id: 12, task_title: "Ship it", project_name: "Launch" },
});

const serveAlert = (redacted: { title: string; body: string } | null = null) => {
  const read = vi.fn();
  server.use(
    http.get("/api/v1/notifications/7/alert", () =>
      HttpResponse.json({ notification: line, redacted })
    ),
    http.post("/api/v1/notifications/7/read", () => {
      read();
      return HttpResponse.json({ ...line, read_at: "2026-01-15T00:01:00Z" });
    })
  );
  return read;
};

describe("useDesktopApp", () => {
  beforeEach(() => {
    desktop.notify.mockClear();
    desktop.setBadge.mockClear();
    desktop.navigate.mockClear();
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a line in the bell's words, and clicking it reads and opens it", async () => {
    const read = serveAlert();
    renderWithProviders(<Probe />);
    await waitFor(() => expect(desktop.clicked).not.toBeNull());

    receiveAlert({ action: "created", ids: { notifications: [7] } });

    await waitFor(() =>
      expect(desktop.notify).toHaveBeenCalledWith({
        title: expect.stringContaining("Ship it"),
        tag: "7",
      })
    );
    desktop.clicked?.({ tag: "7" });
    await waitFor(() => expect(read).toHaveBeenCalled());
    expect(desktop.navigate).toHaveBeenCalledWith({ to: expect.stringContaining("12") });
  });

  it("shows only the kind of thing where details are hidden", async () => {
    serveAlert({ title: "You were assigned a task", body: "Open Initiative to see it." });
    renderWithProviders(<Probe />);
    await waitFor(() => expect(desktop.clicked).not.toBeNull());

    receiveAlert({ action: "created", ids: { notifications: [7] } });

    await waitFor(() =>
      expect(desktop.notify).toHaveBeenCalledWith({
        title: "You were assigned a task",
        body: "Open Initiative to see it.",
        tag: "7",
      })
    );
  });

  it("stays quiet while the window is in front", async () => {
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    serveAlert();
    renderWithProviders(<Probe />);
    await waitFor(() => expect(desktop.clicked).not.toBeNull());

    receiveAlert({ action: "created", ids: { notifications: [7] } });
    receiveAlert({ action: "summary" });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(desktop.notify).not.toHaveBeenCalled();
  });

  it("puts the bell's unread count on the badge", async () => {
    server.use(
      http.get("/api/v1/notifications/", () =>
        HttpResponse.json({ notifications: [line], unread_count: 3, next_cursor: null })
      )
    );
    renderWithProviders(<Probe />);

    await waitFor(() =>
      expect(desktop.setBadge).toHaveBeenLastCalledWith(expect.objectContaining({ count: 3 }))
    );
  });
});
