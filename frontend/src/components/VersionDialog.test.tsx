import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";

import { VersionDialog } from "./VersionDialog";

vi.mock("@/hooks/useSettings", () => ({
  useChangelog: () => ({ data: { entries: [] }, isLoading: false }),
}));

const Footer = () => (
  <VersionDialog currentVersion="1.2.3" latestVersion="1.2.3">
    <button type="button">v1.2.3</button>
  </VersionDialog>
);

describe("VersionDialog", () => {
  it("leads, quietly, to the open-source licences", async () => {
    const user = userEvent.setup();
    const { router } = renderPage(Footer);

    await user.click(await screen.findByRole("button", { name: "v1.2.3" }));
    const link = await screen.findByRole("link", { name: "Open-source licences" });
    expect(link).toHaveAttribute("href", "/licences");

    await user.click(link);
    await waitFor(() => expect(router.state.location.pathname).toBe("/licences"));
    // The dialog closes on the way, so the page is not left behind it.
    await waitFor(() =>
      expect(screen.queryByRole("link", { name: "Open-source licences" })).not.toBeInTheDocument()
    );
  });
});
