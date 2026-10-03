/**
 * When a server's update needs a newer app, the prompt hands over the new app
 * for this device, from the release the update's floor names.
 */
import { Capacitor } from "@capacitor/core";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";
import { androidApkUrl, desktopInstallerUrl } from "@/lib/links";

import { NativeUpdateRequiredDialog } from "./NativeUpdateRequiredDialog";

describe("NativeUpdateRequiredDialog", () => {
  it.each([
    ["android", androidApkUrl("0.80.0")],
    // jsdom says Linux.
    ["electron", desktopInstallerUrl("0.80.0", "linux")],
  ])("offers the new %s app", async (platform, href) => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);
    renderWithProviders(
      <NativeUpdateRequiredDialog
        open
        version="0.81.0"
        minNativeVersion="0.80.0"
        onClose={vi.fn()}
      />
    );

    expect(await screen.findByRole("link", { name: /download/i })).toHaveAttribute("href", href);
  });
});
