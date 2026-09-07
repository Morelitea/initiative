/**
 * The platform owner's community-directory switch.
 *
 * The switch reflects the deployment's boot config rather than a settings read
 * of its own, so the interesting part is that the two stay one value: what the
 * page shows is what every other page reads to decide whether to offer the
 * directory.
 */
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";

const updateMutate = vi.fn();
const config = vi.hoisted(() => ({
  communityDirectory: false,
  ageGate: true,
  defaultDmPolicy: "private" as "private" | "community" | "public",
}));

vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    communityDirectoryEnabled: config.communityDirectory,
    communityAgeGateEnabled: config.ageGate,
    isLoading: false,
  }),
}));

vi.mock("@/hooks/useSettings", () => ({
  useUpdateCommunitySettings: () => ({ mutate: updateMutate, isPending: false }),
  useCommunitySettings: () => ({
    data: {
      community_directory_enabled: config.communityDirectory,
      age_gate_enabled: config.ageGate,
      default_dm_policy: config.defaultDmPolicy,
    },
  }),
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
    config.ageGate = true;
    config.defaultDmPolicy = "private";
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

  const ageToggle = () => screen.getByLabelText("Ask members to confirm they are 13 or older");

  it("starts asking members their age", async () => {
    renderPage();

    expect(
      await screen.findByLabelText("Ask members to confirm they are 13 or older")
    ).toBeChecked();
  });

  it("only stops asking once the owner asserts everyone here is an adult", async () => {
    renderPage();
    fireEvent.click(ageToggle());

    // The switch alone writes nothing — the assertion is the confirmation.
    expect(updateMutate).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Everyone here is 18 or older" }));

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      age_gate_enabled: false,
    });
  });

  it("turns the question back on without asking anything", () => {
    config.ageGate = false;
    renderPage();

    expect(ageToggle()).not.toBeChecked();
    fireEvent.click(ageToggle());

    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: false,
      age_gate_enabled: true,
    });
  });

  it("carries the age gate through a directory toggle unchanged", () => {
    renderPage();
    fireEvent.click(toggle());

    // The directory switch writes only its own half; omitting the other is
    // what leaves the owner's assertion alone.
    expect(updateMutate).toHaveBeenCalledWith({ community_directory_enabled: true });
  });

  it("is not offered below the owner tier", () => {
    renderPage("operator");

    expect(screen.queryByLabelText("Run a community directory")).not.toBeInTheDocument();
    expect(
      screen.getByText("You need the platform owner role to run a community directory.")
    ).toBeInTheDocument();
  });
});

describe("the policy new accounts start on", () => {
  it("shows what this deployment ships with", async () => {
    renderPage();
    expect(await screen.findByLabelText("Direct messages for new accounts")).toHaveTextContent(
      "Private"
    );
  });

  it("changes it without disturbing the directory switch", async () => {
    config.communityDirectory = true;
    renderPage();

    await userEvent.click(screen.getByLabelText("Direct messages for new accounts"));
    await userEvent.click(await screen.findByRole("option", { name: "My communities" }));

    // The directory value is carried through: the endpoint takes it on every
    // write, and this control is not a decision about it.
    expect(updateMutate).toHaveBeenCalledWith({
      community_directory_enabled: true,
      default_dm_policy: "community",
    });
  });
});
