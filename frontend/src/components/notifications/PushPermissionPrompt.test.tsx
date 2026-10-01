import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";

import { PushPermissionPrompt } from "./PushPermissionPrompt";

// The real hook starts Firebase through a Capacitor plugin that jsdom can't load.
vi.mock("@/hooks/usePushNotifications", () => ({
  usePushNotifications: () => ({
    permissionStatus: "prompt",
    requestPermission: vi.fn(),
    isSupported: true,
  }),
}));

describe("PushPermissionPrompt", () => {
  it("waits until a notification is waiting", async () => {
    renderWithProviders(<PushPermissionPrompt />, { auth: { user: buildUser() } });
    // The default handler reports nothing unread.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText("Enable Push Notifications")).not.toBeInTheDocument();
  });

  it("offers once a notification is waiting, though nothing was made here", async () => {
    // Somebody else assigned, mentioned or messaged them: nothing was made here.
    const place = {
      guild_id: 1,
      initiative_id: 1,
      tool: "projects",
      resource_id: 1,
      subject_type: "task",
      subject_id: 1,
    };
    server.use(
      http.get("/api/v1/notifications/unread", () => HttpResponse.json({ places: [place] }))
    );
    renderWithProviders(<PushPermissionPrompt />, { auth: { user: buildUser() } });

    expect(await screen.findByText("Enable Push Notifications")).toBeInTheDocument();
  });
});
