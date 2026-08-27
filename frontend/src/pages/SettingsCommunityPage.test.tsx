/**
 * The platform owner's community-directory switch.
 *
 * The switch reflects the deployment's boot config rather than a settings read
 * of its own, so the interesting part is that the two stay one value: what the
 * page shows is what every other page reads to decide whether to offer the
 * directory.
 */
import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const updateMutate = vi.fn();
const config = vi.hoisted(() => ({ communityDirectory: false }));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    communityDirectoryEnabled: config.communityDirectory,
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useSettings", () => ({
  useUpdateCommunitySettings: () => ({ mutate: updateMutate, isPending: false }),
}));

import { SettingsCommunityPage } from "./SettingsCommunityPage";

const renderPage = (role: "owner" | "operator" = "owner") =>
  renderWithProviders(<SettingsCommunityPage />, {
    auth: { user: buildUser({ role }) },
  });

const toggle = () => screen.getByLabelText("Run a community directory");

describe("SettingsCommunityPage", () => {
  beforeEach(() => {
    updateMutate.mockClear();
    config.communityDirectory = false;
  });

  it("starts off, matching a deployment that has never turned it on", async () => {
    renderPage();

    expect(await screen.findByLabelText("Run a community directory")).not.toBeChecked();
  });

  it("turns the directory on", async () => {
    renderPage();
    fireEvent.click(await screen.findByLabelText("Run a community directory"));

    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: true });
  });

  it("turns it back off", async () => {
    config.communityDirectory = true;
    renderPage();

    expect(toggle()).toBeChecked();
    fireEvent.click(toggle());

    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: false });
  });

  it("is not offered below the owner tier", () => {
    renderPage("operator");

    expect(screen.queryByLabelText("Run a community directory")).not.toBeInTheDocument();
    expect(
      screen.getByText("You need the platform owner role to run a community directory.")
    ).toBeInTheDocument();
  });
});
